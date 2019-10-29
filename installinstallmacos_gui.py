#!/System/Library/Frameworks/Python.framework/Versions/Current/Resources/Python.app/Contents/MacOS/Python
# -*- coding: utf-8 -*-
#
# Copyright 2019 Glynn Lane (primalcurve)
#
# Based on installinstallmacos.py
# Copyright 2017 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Thanks to Tim Sutton for ideas, suggestions, and sample code.
#

"""installinstallmacos.py
A tool to download the parts for an Install macOS app from Apple's
softwareupdate servers and install a functioning Install macOS app onto an
empty disk image"""

# Remove any other detected paths to prevent issues with incompatible versions
# of PyObjC.
import sys
sys.path = [p for p in sys.path if p[1:6] != "Users" and p[1:8] != "Library"]
# Make sure sys.path includes the necessary paths to import the various
# modules needed for this script.
PYTHON_FRAMEWORK = (
    "/System/Library/Frameworks/Python.framework/Versions/2.7/")
PYTHON_FRAMEWORK_PATHS = [
    PYTHON_FRAMEWORK + "lib/python27.zip",
    PYTHON_FRAMEWORK + "lib/python2.7",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-darwin",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-mac",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-mac/lib-scriptpackages",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-tk",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-old",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-dynload",
    PYTHON_FRAMEWORK + "Extras/lib/python",
    PYTHON_FRAMEWORK + "Extras/lib/python/PyObjC"
]
for path in PYTHON_FRAMEWORK_PATHS:
    if path not in sys.path:
        sys.path.append(path)

import argparse
import json
import logging
import logging.handlers
import glob
import gzip
import math
import objc
import os
import plistlib
import Queue
import signal
import subprocess
import threading
import time
import urlparse
import urllib2
from xml.dom import minidom
from xml.parsers.expat import ExpatError
from SystemConfiguration import SCDynamicStoreCopyLocalHostName


from Foundation import (
    NSObject,
    NSString,
    NSTimer,
)

# put all AppKit imports used by the project here
from AppKit import (
    NSAlert,
    NSApp,
    NSApplication,
    NSAutoreleasePool,
    NSBundle,
    NSClosableWindowMask,
    NSCriticalAlertStyle,
    NSFont,
    NSImage,
    NSImageView,
    NSInformationalAlertStyle,
    NSMiniaturizableWindowMask,
    NSProgressIndicator,
    NSProgressIndicatorSpinningStyle,
    NSResizableWindowMask,
    NSScreenSaverWindowLevel,
    NSTextField,
    NSTitledWindowMask,
    NSWindow,
    NSWindowController
)

from PyObjCTools import AppHelper


DEFAULT_PROGRESS_STRING = NSString.stringWithString_(u"Beginning Process...")

DEFAULT_SUCATALOGS = {
    "17": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
    "18": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.14-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
    "19": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.15-10.14-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
}

SEED_CATALOGS_PLIST = (
    "/System/Library/PrivateFrameworks/Seeding.framework/Versions/Current/"
    "Resources/SeedCatalogs.plist"
)

DEFAULT_WORKING_DIR = ("/private/tmp")

USER_AGENT = (
    "MacAppStore/3.0 (Macintosh; OS X 10.14.3; 18D109) AppleWebKit/14606.4.5")

CACHE_LOCATOR = ("/usr/bin/AssetCacheLocatorUtil")

CUSTOM_ICNS = ("None")
SU_ICNS = ("/System/Library/CoreServices/Software Update.app/Contents/" +
           "Resources/SoftwareUpdate.icns")
APP_ICNS = ("/Applications/App Store.app/Contents/Resources/AppIcon.icns")

# Set progress bars to max out at 100, which allows for more granularity.
PROGRESS_BAR_MAX_VALUE = 100.0
# Weight of different stages of the process.
METADATA_WEIGHT = (1.0 / 100.0)
CATALOG_WEIGHT = (2.0 / 100.0)
PRODUCT_INFO_WEIGHT = (2.0 / 100.0)
PRODUCT_WEIGHT = (74.0 / 100.0)

# Custom Log Levels.
## These are set between logging.INFO (20) and logging.WARN (30) purposefully.
SLVL = 16
OLVL = 24
FAIL = 42

# Logging Config
SCRIPT_NAME = ("installinstallmacos")
logger = logging.getLogger(SCRIPT_NAME)
logger.setLevel(logging.DEBUG)

## Some initial setup
### Create a reverse domain name for the program folders
R_DOMAIN = ("com.github.primalcurve")
LONG_R_DOMAIN = R_DOMAIN + "." + SCRIPT_NAME
### Create paths to the logs and cache.
LOG_PARENT_DIR = os.path.join(
    DEFAULT_WORKING_DIR, R_DOMAIN, LONG_R_DOMAIN)
SCRIPT_CACHE = os.path.join(
    DEFAULT_WORKING_DIR, R_DOMAIN, LONG_R_DOMAIN)
### Make the directories if they do not exist.
if not os.path.exists(LOG_PARENT_DIR):
    os.makedirs(LOG_PARENT_DIR)
if not os.path.exists(SCRIPT_CACHE):
    os.makedirs(SCRIPT_CACHE)
### Create the name of the log file for the logger.
LOG_FILE = os.path.join(LOG_PARENT_DIR, LONG_R_DOMAIN + ".log")

## Configure the logger object.
### Custom Log Levels:
logging.addLevelName(OLVL, "Overall")
logging.addLevelName(SLVL, "Stage")
logging.addLevelName(FAIL, "Failure")

### logging Formatters
easy_formatter = logging.Formatter("%(message)s")
file_formatter = logging.Formatter(
    "%(asctime)s|func:%(funcName)s|" +
    "line:%(lineno)s|%(message)s")
### Defining the different Log StreamHandlers
log_stderr = logging.StreamHandler()
#### Rotate the log file every 1 day 5 times before deleting.
log_logfile = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when="D", interval=1, backupCount=5)
### Defining different log levels for each StreamHandler
#### Only log INFO and above logging events to stderr
log_stderr.setLevel(logging.INFO)
#### Log all messages with DEBUG and above to the logfile.
log_logfile.setLevel(logging.DEBUG)
### Add formatters to logging Handlers.
log_stderr.setFormatter(easy_formatter)
log_logfile.setFormatter(file_formatter)
### Add all of the handlers to this logging instance:
logger.addHandler(log_stderr)
logger.addHandler(log_logfile)


class ReplicationError(Exception):
    """A custom error when replication fails"""
    pass


class ErrorSheet(NSAlert):
    sheet_parent = None

    def init(self, *args, **kwargs):
        # Call the super class (ErrorSheet)
        self = objc.super(ErrorSheet, self).init(*args, **kwargs)
        return self

    def setParent(self, window):
        self.sheet_parent = window

    def displayMessage(self, title, message, type=NSInformationalAlertStyle):
        def errorClose(returncode):
            self.sheet_parent.close()

        self.setMessageText_(title)
        self.setInformativeText_(message)
        self.setAlertStyle_(type)
        self.addButtonWithTitle_(NSString.stringWithString_("Exit"))
        self.beginSheetModalForWindow_completionHandler_(
            self.sheet_parent, errorClose)

    def destroy(self):
        self = None


# This metadata is missing from PyObjC, so it has to be created here.
objc.registerMetaDataForSelector(
    b"NSAlert", b"beginSheetModalForWindow:completionHandler:",
    dict(arguments={3: {"callable": {"retval":
                                     {"type": b"v"},
                                     "arguments":
                                     {0: {"type": b"^v"},
                                      1: {"type": b"q"}}}}}))


class StatusText(NSTextField):
    def initWithFrame_(self, *args, **kwargs):
        # Call the super class (NSTextField)
        self = objc.super(StatusText, self).initWithFrame_(*args, **kwargs)
        self.setStringValue_(
            NSString.stringWithString_(u"Progress Bar"))
        self.setBezeled_(False)
        self.setDrawsBackground_(False)
        self.setSelectable_(False)
        self.setFont_(NSFont.systemFontOfSize_(14))
        return self


class ProgressSpinner(NSProgressIndicator):
    def initWithFrame_(self, *args, **kwargs):
        # Call the super class (NSProgressIndicator)
        self = objc.super(ProgressSpinner,
                          self).initWithFrame_(*args, **kwargs)
        self.setStyle_(NSProgressIndicatorSpinningStyle)
        self.setIndeterminate_(True)


class ProgressBar(NSProgressIndicator):
    def initWithFrame_(self, *args, **kwargs):
        # Call the super class (NSProgressIndicator)
        self = objc.super(ProgressBar, self).initWithFrame_(*args, **kwargs)
        self.setIndeterminate_(False)
        self.setMinValue_(0.0)
        self.setMaxValue_(PROGRESS_BAR_MAX_VALUE)
        return self


class ProgressWindow(NSWindowController):
    # Class Attributes
    window = NSWindow.alloc()
    window_icon = NSImageView.alloc()
    window_icon_file = NSImage.alloc()
    updateTimer = None
    overall_pbar = ProgressBar.alloc()
    stage_pbar = ProgressBar.alloc()
    spinner = ProgressSpinner.alloc()
    errorSheet = ErrorSheet.alloc()
    overall_text = StatusText.alloc()
    stage_text = StatusText.alloc()
    version_text = StatusText.alloc()
    versionText = NSString.stringWithString_(u"Progress Window")
    # This style mask prevents the window from being resized or minimized.
    style_mask = (
        NSTitledWindowMask | NSClosableWindowMask &
        ~NSResizableWindowMask & ~NSMiniaturizableWindowMask)

    def init(self, *args, **kwargs):
        self = objc.super(ProgressWindow, self).init(*args, **kwargs)
        self.queue = Queue.Queue()
        return self

    def showProgressWindow(self):
        logger.debug("Configuring main window.")
        frame = ((0.0, 0.0), (480.0, 240.0))
        self.window.initWithContentRect_styleMask_backing_defer_(
            frame, ProgressWindow.style_mask, 2, 0)
        self.window.setCanBecomeVisibleWithoutLogin_(True)
        self.window.setLevel_(NSScreenSaverWindowLevel - 1)
        self.window.center()
        self.window.setTitle_("Downloading macOS")

        # Use a pretty icon to make the window look more composed.
        self.window_icon_file.initByReferencingFile_(self._findIcon())

        logger.debug("Finished setting up main window. Defining subelements.")
        # Layout. Each frame element is a rectangle defined as:
        # ((x offset from origin, y offset from origin), (width, height))
        # where origin is the top left corner of the window.
        self.window_icon.initWithFrame_(((10.0, 165.0), (60.0, 60.0)))
        self.overall_pbar.initWithFrame_(((10.0, 95.0), (460.0, 20.0)))
        self.overall_text.initWithFrame_(((10.0, 115.0), (460.0, 40.0)))
        self.stage_pbar.initWithFrame_(((10.0, 15.0), (460.0, 20.0)))
        self.stage_text.initWithFrame_(((10.0, 35.0), (460.0, 40.0)))

        logger.debug("Adding subelements to main window.")
        self.window_icon.setImage_(self.window_icon_file)
        self.window.contentView().addSubview_(self.window_icon)
        self.window.contentView().addSubview_(self.overall_pbar)
        self.window.contentView().addSubview_(self.overall_text)
        self.window.contentView().addSubview_(self.stage_pbar)
        self.window.contentView().addSubview_(self.stage_text)

        logger.debug("Done setting up window. Now displaying.")
        self.window.display()
        self.window.orderFrontRegardless()

    def showVersionInfo(self, text):
        self.version_text.initWithFrame_(((80.0, 165.0), (460.0, 40.0)))
        self.version_text.setFont_(NSFont.systemFontOfSize_(18))
        self.window.contentView().addSubview_(self.version_text)
        self.version_text.setStringValue_(
            NSString.stringWithString_(text))
        self.version_text.displayIfNeeded()

    def startQueueLoop(self):
        # Display and continuously update elements of the main window.
        self.stopQueueLoop()
        # Run the incoming items once.
        self.runAnyIncomingItems()
        # Kick off a timer that checks the queue periodically.
        self.updateTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1,
            self,
            u"runAnyIncomingItems",
            None,
            True
        )

    def stopQueueLoop(self):
        # Stop the update timer.
        if self.updateTimer is not None:
            self.updateTimer.invalidate()
            self.updateTimer = None

    def runAnyIncomingItems(self):
        """Handle all the callables currently in the queue (if any)."""
        while self.queue.qsize():
            pool = NSAutoreleasePool.alloc().init()
            try:
                new_method, new_args, new_kwargs = self.queue.get(0)
                logger.debug(
                    "Method: %s Args: %s Kwargs: %s" %
                    (str(new_method), str(new_args), str(new_kwargs)))
                new_method(*new_args, **new_kwargs)
                self.queue.task_done()
            except Queue.Empty:
                pass
            del pool

    def haltOnError(self, message):
        self.errorSheet.init()
        self.errorSheet.setParent(self.window)
        title = "macOS Install"
        alert_type = NSCriticalAlertStyle
        self.errorSheet.displayMessage(title, message, alert_type)
        self.stopQueueLoop()

    def _findIcon(self):
        for icon in [CUSTOM_ICNS, SU_ICNS, APP_ICNS]:
            if os.path.exists(icon):
                logger.debug("Using Icon: " + icon)
                return icon

    def changeOverallText(self, text):
        self.overall_text.setStringValue_(
            NSString.stringWithString_(text))
        self.overall_text.displayIfNeeded()

    def changeStageText(self, text):
        self.stage_text.setStringValue_(
            NSString.stringWithString_(text))
        self.stage_text.displayIfNeeded()

    def changeOverallProgress(self, progress):
        logger.debug(
            "GUI Current Progress Overall: %f Incrementing by: %f" %
            (self.overall_pbar.doubleValue(), progress))
        self.overall_pbar.incrementBy_(progress)

    def changeStageProgress(self, progress):
        logger.debug(
            "GUI Current Progress Stage: %f Incrementing by: %f" %
            (self.stage_pbar.doubleValue(), progress))
        self.stage_pbar.incrementBy_(progress)

    def resetStageProgress(self):
        self.stage_pbar.setDoubleValue_(0.0)

    def showSpinner(self):
        # Remove Stage-related Objects:
        main_subviews = [
            self.stage_pbar, self.stage_text, self.overall_pbar]
        for view in main_subviews:
            view.removeFromSuperview()
        self.spinner.initWithFrame_(((200.0, 30.0), (80.0, 80.0)))
        self.window.contentView().addSubview_(self.spinner)
        self.spinner.startAnimation_(True)
        self.spinner.displayIfNeeded()


class AppDelegate(NSObject):
    def init(self, *args, **kwargs):
        self = objc.super(AppDelegate, self).init(*args, **kwargs)
        self.progress_window = ProgressWindow.alloc().init()
        return self

    def applicationDidFinishLaunching_(self, aNotification):
        self.progress_window.showProgressWindow()
        self.progress_window.startQueueLoop()

    def applicationShouldTerminateAfterLastWindowClosed_(self, aNotification):
        return True


class ScriptThread(object):
    """Object that creates a separate thread for the underlying process, and
    controls the program flow into the GUI, making sure that the GUI is fed
    methods in the correct way so that it does not lock up.
    """
    def __init__(self, arguments, gui=None):
        """Basic Initialization. Nothing runs until start_script is called.
        """
        self.arguments = arguments
        self.queue = None
        self.gui = gui

        # Set up the GUI part if necessary.
        if gui:
            self.gui.end_command = self.end_application

        self.running = True

    def start_script(self):
        logger.info("Starting Script!")
        self.overall_text("Starting script.")
        self.thread1 = threading.Thread(target=self.script_thread)
        self.thread1.start()

    def script_thread(self):
        install_macos(self.arguments, self)
        self.end_application()

    def enqueue(self, method, *args, **kwargs):
        self.queue.put((method, args, kwargs))

    def script_error(self, message):
        if self.gui:
            self.enqueue(self.gui.haltOnError, message)

    def version_text(self, text):
        if self.gui:
            self.enqueue(self.gui.showVersionInfo, text)

    def overall_text(self, text):
        if self.gui:
            self.enqueue(self.gui.changeOverallText, text)

    def stage_text(self, text):
        if self.gui:
            self.enqueue(self.gui.changeStageText, text)

    def overall_progress(self, progress):
        if self.gui:
            self.enqueue(self.gui.changeOverallProgress, progress)

    def stage_progress(self, progress):
        if self.gui:
            self.enqueue(self.gui.changeStageProgress, progress)

    def reset_stage_progress(self):
        logger.debug("Resetting the Stage Progress Bar!")
        if self.gui:
            self.enqueue(self.gui.resetStageProgress)

    def show_spinner(self):
        logger.debug("Switching to Indeterminate Progress Indicator.")
        if self.gui:
            self.enqueue(self.gui.showSpinner)

    def wait_for_the_end(self):
        time_slept = 0
        logger.debug("Waiting for signal...")
        while self.running:
            time.sleep(1)
            logger.debug("Still waiting...")
            time_slept += 1
        self.end_application()

    def receive_signal(self, signal_number, stack_frame):
        logger.debug("Got signal! %s Frame: %s" %
                     (str(signal_number), str(stack_frame)))
        self.running = False

    def end_application(self):
        logger.debug("Ending Application.")
        if self.gui:
            self.enqueue(self.gui.stopQueueLoop)
        self.running = False
        if self.gui:
            self.gui.window.performClose_(True)
        sys.exit(0)


class MakeInstaller(object):
    """Object that encapsulates the methods and data required to download and
    install macOS.
    """
    def __init__(self, arguments, script_thread=None):
        self.script_thread = script_thread
        self.arguments = arguments
        self.this_mac = MacInfo()
        self.software_catalog = SoftwareCatalog(self)
        self.target_version = None

    def replicate_product(self):
        """Downloads all the packages for a product"""
        self.script_thread.reset_stage_progress()
        self.product = (
            self.software_catalog.catalog["Products"][self.target_version])
        # We will need total_size to calculate our progress.
        total_size = float(sum(
            [size.get("Size", "0") for size in self.product.get("Packages")
             if "URL" in size]))
        for package in self.product.get("Packages", []):
            self.script_thread.reset_stage_progress()
            package_size = float(package.get("Size"))
            relative_weight = ((package_size / total_size) * PRODUCT_WEIGHT)
            logger.debug("Package Size: %f Total Size: %f Weight: %f" %
                         (package_size, total_size, relative_weight))
            if "URL" in package:
                try:
                    replicate_url(
                        self.script_thread, package["URL"], relative_weight, 
                        caching_server=self.arguments.caching_server,
                        root_dir=self.arguments.workdir)
                except ReplicationError as err:
                    logger.log(FAIL, "Could not replicate %s: %s" %
                               (package["URL"], err))
            if "MetadataURL" in package:
                try:
                    replicate_url(
                        self.script_thread, package["MetadataURL"],
                        relative_weight,
                        caching_server=self.arguments.caching_server,
                        root_dir=self.arguments.workdir)
                except ReplicationError as err:
                    logger.log(FAIL, "Could not replicate %s: %s" %
                               (package["MetadataURL"], err))

    def install_product(self):
        """Verify the installation of the product."""
        if not self._install_product():
            logger.log(OLVL, "Product installation failed. Redownloading.")
            self.replicate_product()
        if not self._install_product():
            logger.log(FAIL, "Unable to create installer!")
        self.os_install = glob.glob("/Applications/Install macOS *.app" +
                                    "/Contents/Resources/startosinstall")[0]

    def _install_product(self):
        """Install the product to the Applications folder."""
        dist_path = (self.software_catalog.product_info[
                     self.target_version]["DistributionPath"])
        cmd = ["/usr/sbin/installer", "-pkg", dist_path, "-target", "/"]
        try:
            subprocess.check_call(cmd)
            return True
        except subprocess.CalledProcessError as err:
            logger.error(str(err))
            return False

    def launch_osinstall(self):
        ## subprocess.Popen is used here without its .communicate() method.
        ## This is intentional. This immediately releases the file descriptor
        ## to the underlying process, allowing this script to exit before
        ## startosinstall is complete.
        self.script_thread.overall_progress(PROGRESS_BAR_MAX_VALUE)
        this_pid = os.getpid()
        logger.debug("This PID: " + str(this_pid))
        # Request that startosinstall signals this script when it is complete.
        os_install_cmd = [self.os_install, "--agreetolicense",
                          "--pidtosignal", str(this_pid),
                          "--rebootdelay", "30"]
        if self.arguments.erase_install == "ERASEINSTALL":
            os_install_cmd.append("--eraseinstall")
            logger.log(OLVL, "Starting Erase Install!")
        else:
            logger.log(OLVL, "Starting In-Place Installation!")

        time.sleep(15)
        logger.debug("startosinstall will run with the following options: %s" %
                     " ".join(os_install_cmd))
        # Start Popen without .communicate() so the fd is decoupled
        # from this pid.
        subprocess.Popen(os_install_cmd)


class SoftwareCatalog(object):
    """Object that encapsulates the definition of the software catalog
    """
    def __init__(self, parent):
        self.parent = parent
        self.this_mac = self.parent.this_mac
        self.script_thread = self.parent.script_thread
        self.arguments = self.parent.arguments
        self.workdir = self.arguments.workdir
        # Prepping instance variables.
        self.os_installers = []
        self.product_info = {}

    def start_parsing(self):
        self.script_thread.reset_stage_progress()
        self.get_catalog_url()
        logger.debug("su_catalog_url: " + self.su_catalog_url)
        self.download_sucatalog()
        logger.debug("local_path: " + self.local_path)
        self.parse_sucatalog()
        logger.debug("catalog: " + str(self.catalog))
        self.find_mac_os_installers()
        logger.debug("os_installers: " + str(self.os_installers))
        self.os_installer_product_info()
        logger.debug("product_info: " + str(self.product_info))

    def get_catalog_url(self):
        if self.arguments.catalogurl:
            self.su_catalog_url = self.arguments.catalogurl
        else:
            self.su_catalog_url = get_default_catalog()
        if not self.su_catalog_url:
            logger.log(FAIL, "Could not find a default catalog url " +
                       "for this OS version.")
            sys.exit(1)

    def download_sucatalog(self):
        """Downloads the softwareupdate catalog"""
        try:
            self.local_path = replicate_url(self.script_thread,
                                            self.su_catalog_url,
                                            CATALOG_WEIGHT,
                                            root_dir=self.workdir)
        except ReplicationError as err:
            logger.error("Could not replicate %s: %s" %
                         (self.su_catalog_url, err))

    def parse_sucatalog(self):
        if os.path.splitext(self.local_path)[1] == ".gz":
            with gzip.open(self.local_path) as the_file:
                content = the_file.read()
                try:
                    self.catalog = plistlib.readPlistFromString(content)
                except ExpatError as err:
                    logger.log(FAIL, "Error reading %s: %s" %
                               (self.local_path, err))
        else:
            try:
                self.catalog = plistlib.readPlist(self.local_path)
            except (OSError, IOError, ExpatError) as err:
                logger.error("Error reading %s: %s" %
                             (self.local_path, err))

    def find_mac_os_installers(self):
        """Creates a list of product identifiers for what appear to be macOS
        installers"""
        if "Products" in self.catalog:
            product_keys = list(self.catalog["Products"].keys())
            for product_key in product_keys:
                product = self.catalog["Products"][product_key]
                try:
                    if product["ExtendedMetaInfo"][
                            "InstallAssistantPackageIdentifiers"][
                            "OSInstall"] == "com.apple.mpkg.OSInstall":
                        self.os_installers.append(product_key)
                except KeyError:
                    continue

    def os_installer_product_info(self):
        """Creates a dict of info about products that look like macOS
        installers"""
        for product_key in self.os_installers:
            self.product_info[product_key] = {}
            filename = self.get_server_metadata(product_key)
            self.product_info[product_key] = parse_server_metadata(filename)
            product = self.catalog["Products"][product_key]
            self.product_info[product_key]["PostDate"] = product["PostDate"]
            distributions = product["Distributions"]
            dist_url = distributions.get("English") or distributions.get("en")
            try:
                dist_path = replicate_url(self.script_thread, dist_url,
                                          PRODUCT_INFO_WEIGHT,
                                          root_dir=self.workdir)
            except ReplicationError as err:
                logger.log(FAIL, "Could not replicate %s: %s" %
                           (dist_url, err))
            dist_info = parse_dist(dist_path)
            if dist_info.get("nonSupportedModels"):
                # Remove any incompatible installer.
                if (self.this_mac.machine_model in
                   dist_info.get("nonSupportedModels")):
                    logger.debug(
                        "%s is not compatible with this installer." %
                        self.this_mac.machine_model)
                    del self.product_info[product_key]
                    continue
                logger.debug(
                    "%s is not listed as incompatible with this installer." %
                    self.this_mac.machine_model)

            self.product_info[product_key]["DistributionPath"] = dist_path
            self.product_info[product_key].update(dist_info)

    def get_server_metadata(self, product_key):
        """Replicate ServerMetaData"""
        try:
            url = self.catalog["Products"][product_key]["ServerMetadataURL"]
            try:
                return replicate_url(self.script_thread, url, METADATA_WEIGHT,
                                     root_dir=self.workdir)
            except ReplicationError as err:
                logger.error("Could not replicate %s: %s" % (url, err))
                return None
        except KeyError:
            logger.log(FAIL, "Malformed catalog.")
            return None


class MacInfo(object):
    """Object that encapsulates information about this computer.
    """
    def __init__(self):
        self._sp_hardware = subprocess.check_output(
            ["/usr/sbin/system_profiler", "SPHardwareDataType", "-xml"])
        self.sp_hardware = plistlib.readPlistFromString(self._sp_hardware)[0]
        _items = [i for i in self.sp_hardware.get("_items")
                  if "serial_number" in i.keys()][0]
        for key, value in _items.iteritems():
            if key[0] != "_":
                self.__dict__[key] = value

    def _network(self):
        self.computer_name = SCDynamicStoreCopyComputerName(None, None)[0]
        self.local_hostname = SCDynamicStoreCopyLocalHostName(None)


# Custom logging Filters
class OverallFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == OLVL


class StageFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == SLVL


# Custom logging Handlers
class GUIText(logging.StreamHandler):
    def __init__(self, text_method, *args, **kwargs):
        logging.StreamHandler.__init__(self, *args, **kwargs)
        self.text_method = text_method

    def emit(self, record):
        msg = self.format(record)
        self.text_method(msg)


def get_default_catalog():
    """Returns the default softwareupdate catalog for the current OS"""
    darwin_major = os.uname()[2].split(".")[0]
    logger.debug("Major macOS Version: " + darwin_major)
    return DEFAULT_SUCATALOGS.get(darwin_major)


def parse_server_metadata(filename):
    """Parses a softwareupdate server metadata file, looking for
    information of interest.
    Returns a dictionary containing title, version, and description."""
    title = ""
    vers = ""
    try:
        md_plist = plistlib.readPlist(filename)
    except (OSError, IOError, ExpatError) as err:
        logger.error("Error reading " + filename + str(err))
        return {}
    vers = md_plist.get("CFBundleShortVersionString", "")
    localization = md_plist.get("localization", {})
    preferred_localization = (localization.get("English") or
                              localization.get("en"))
    if preferred_localization:
        title = preferred_localization.get("title", "")

    metadata = {}
    metadata["title"] = title
    metadata["version"] = vers
    return metadata


def parse_dist(filename):
    """Parses a softwareupdate dist file, returning a dict of info of
    interest"""
    try:
        dom = minidom.parse(filename)
    except ExpatError:
        logger.log(FAIL, "Invalid XML in %s" % filename)
        return {}
    except IOError as err:
        logger.log(FAIL, "Error reading %s: %s" % (filename, err))
        return {}

    auxinfo = dom.getElementsByTagName("auxinfo")[0]
    scripts = [s for s in dom.getElementsByTagName("script")
               if s.hasChildNodes]
    if auxinfo:
        aux = parse_auxinfo(auxinfo)
        aux.update(parse_scripts(scripts))
        return aux
    else:
        return parse_scripts(scripts)


def parse_auxinfo(auxinfo):
    aux_info = {}
    key = None
    value = None
    children = auxinfo.childNodes
    # handle the possibility that keys from auxinfo may be nested
    # within a "dict" element
    dict_nodes = [n for n in auxinfo.childNodes
                  if n.nodeType == n.ELEMENT_NODE and
                  n.tagName == "dict"]
    if dict_nodes:
        children = dict_nodes[0].childNodes
    for node in children:
        if node.nodeType == node.ELEMENT_NODE and node.tagName == "key":
            key = node.firstChild.wholeText
        if node.nodeType == node.ELEMENT_NODE and node.tagName == "string":
            value = node.firstChild.wholeText
        if key and value:
            aux_info[key] = value
            key = None
            value = None

    logger.debug(str(aux_info))
    return aux_info


def parse_scripts(xml):
    script_info = {}
    # Pull script text from xml:
    scripts = [s.nodeValue for x in xml for s in x.childNodes if s.nodeValue]
    for script in scripts:
        # Get list of nonSupportedModels:
        script_info["nonSupportedModels"] = [
            m.strip("'") for m in
            [t[27:-3] for t in script.splitlines()
                if "var nonSupportedModels =" in t][0].split("','")]
    logger.debug(str(script_info))
    return script_info


def discover_caching_server():
    """Finds caching server using AssetCacheLocatorUtil"""
    try:
        with open(os.devnull, 'w') as DEVNULL:
            cache_json = json.loads(subprocess.Popen(
                [CACHE_LOCATOR, "--json"],
                stdout=subprocess.PIPE, stderr=DEVNULL).communicate()[0])
        logger.debug("AssetCacheLocatorUtil JSON: " + str(cache_json))
    except subprocess.CalledProcessError:
        return False

    try:
        cache_results = (
            cache_json.get("results", {}).get("system", {})
            .get("refreshed servers", {}).get("shared caching"))
        logger.debug("Processed Results JSON: " + str(cache_results))

        if cache_results:
            cache_rank = 100
            caching_server = False
            for cache in cache_results:
                if cache["rank"] < cache_rank:
                    caching_server = cache["hostport"]
                    cache_rank = cache["rank"]

            logger.debug("Discovered caching server: %s" % caching_server)
            return caching_server
        else:
            return False

    except KeyError:
        return False


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def progress_percent(percent):
    return float(percent / 100.0 * PROGRESS_BAR_MAX_VALUE)


def progress_increment(fraction):
    return float(fraction * PROGRESS_BAR_MAX_VALUE)


def replicate_url(script_thread, full_url, weight, root_dir="/tmp",
                  caching_server=None, chunk_size=8196):
    """Downloads a URL and stores it in the same relative path on our
    filesystem. Returns a path to the replicated file."""
    path = urlparse.urlsplit(full_url)[2]
    backup_url = full_url
    if caching_server and (".pkg" in path or ".dmg" in path):
        full_url = (urlparse.urlsplit(full_url)[0] + "://" +
                    caching_server + path + "?source=" +
                    urlparse.urlsplit(full_url)[1])
    relative_url = path.lstrip("/")
    relative_url = os.path.normpath(relative_url)
    local_file_path = os.path.join(root_dir, relative_url)
    if not os.path.exists(os.path.dirname(local_file_path)):
        os.makedirs(os.path.dirname(local_file_path), 0o777)
    file_name = full_url.split("/")[-1].split("?")[0]
    logger.debug("Downloading %s..." % full_url)
    logger.log(SLVL, "Downloading %s..." % file_name)
    with open(local_file_path, "wb") as f:
        headers = {"user-agent": USER_AGENT}
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        # Attempt the download. If 404 or other error is found, try again
        # with the backup_url (which may still fail). The most cromulent
        # usage of this will be if the caching server lacks the files.
        try:
            request = urllib2.Request(full_url, headers=headers)
            response = urllib2.urlopen(request, context=context)
        except urllib2.HTTPError:
            full_url = backup_url
            request = urllib2.Request(full_url, headers=headers)
            response = urllib2.urlopen(request, context=context)
        total = float(response.headers.get("content-length"))
        total_written = 0.0
        diff = 0.0
        if total is None:  # no content length header
            f.write(response.content)
        else:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                written = float(len(chunk))
                total_written += written
                diff += written
                if diff >= 0.01 * total and total >= 5000000:
                    logger.log(
                        SLVL, "Downloading %s   %s of %s" % (
                            file_name, convert_size(total_written),
                            convert_size(total)))
                    script_thread.stage_progress(
                        progress_increment(diff / total))
                    script_thread.overall_progress(
                        progress_increment((diff * weight) / total))
                    diff = 0
    logger.log(SLVL, "Downloading %s Complete." % file_name)
    script_thread.stage_progress(PROGRESS_BAR_MAX_VALUE)
    return local_file_path


def get_latest_macos_version(product_info):
    return sorted([product_info[prod_id]["version"]
                  for prod_id in product_info])[-1]


def matching_product_id(product_info, target):
    all_pids = [prod_id for prod_id in product_info
                if target in product_info[prod_id]['version'] or
                target.lower() in product_info[prod_id]['title'].lower()]

    # If there are more than one product ID, get the newest one.
    if len(all_pids) > 1:
        # Start with the first Product ID in the list.
        newest_pid = all_pids[0]
        for this_pid in all_pids:
            # Convert product ID into an integer (after removing minus signs).
            # If that integer is greater, it is a newer product ID.
            if (int(this_pid.replace("-", "")) >
               int(newest_pid.replace("-", ""))):
                newest_pid = this_pid
                continue
            # plistlib automatically converts date stamps in plists to
            # datetime objects. Grab those for comparison.
            this_date = (product_info[this_pid]["PostDate"])
            new_date = (product_info[newest_pid]["PostDate"])
            # If the date in this loop is greater, use that product ID.
            if this_date > new_date:
                newest_pid = this_pid
        # Now that we've parsed the product IDs for the newest one, return it.
        return newest_pid
    # If there's only one product ID, just return that.
    elif len(all_pids) == 1:
        return all_pids[0]
    else:
        logger.error("Unable to find target version: " + target)
        return None


def parse_version_string(product_info, target):
    return ("%s %s - Dated: %s" % (
        product_info[target]["title"],
        product_info[target]["version"],
        product_info[target]["PostDate"].strftime("%m-%d-%Y")))


def has_apfs():
    try:
        apfs_check = subprocess.check_output(
            ["/usr/sbin/diskutil", "apfs", "list"]).strip()
        if apfs_check == "No APFS Containers found":
            return False
        else:
            return True
    except subprocess.CalledProcessError:
        return False


def setup_logging(script_thread):
    # Add a GUI element to the logger.
    ### Defining the GUI StreamHandlers
    ### This links the ScriptThread class instance to logger, allowing
    ### Threadsafe handling of logging messages in the GUI.
    log_overall = GUIText(script_thread.overall_text)
    log_stage = GUIText(script_thread.stage_text)
    log_fail = GUIText(script_thread.script_error)

    ### Defining different log levels for each StreamHandler
    #### Only log INFO and above logging events to stderr
    log_overall.setLevel(OLVL)
    log_stage.setLevel(SLVL)
    log_fail.setLevel(FAIL)

    ### Add Custom Filters to levels.
    log_overall.addFilter(OverallFilter())
    log_stage.addFilter(StageFilter())

    ### Add formatters to logging Handlers.
    log_overall.setFormatter(easy_formatter)
    log_stage.setFormatter(easy_formatter)
    log_fail.setFormatter(easy_formatter)

    ### Add all of the handlers to this logging instance:
    logger.addHandler(log_overall)
    logger.addHandler(log_stage)
    logger.addHandler(log_fail)


def get_arguments():
    # Returns the results of the argparse module reading argv.
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-gui", default=True,
                        help="Whether or not to show GUI to logged in user.")
    parser.add_argument("--catalogurl", default="",
                        help="Software Update catalog URL. This option "
                        "overrides any seedprogram option.")
    parser.add_argument("--workdir", metavar="path_to_working_dir",
                        default=DEFAULT_WORKING_DIR,
                        help="Path to working directory on a volume with over "
                        "over 10G of available space. Defaults to current "
                        "working directory.")
    parser.add_argument("--target-version",
                        help="Choose which version of macOS to target. "
                        "The latest version will be automatically "
                        "selected.")
    parser.add_argument("--erase-install", default=False,
                        help="Choose whether or not to erase the disk "
                        "when installing macOS. Dangerous!")
    parser.add_argument("--caching-server",
                        help="Specify a caching server (optional)")
    parser.add_argument("--installer-only", default=False,
                        help="Only create the installer.")

    # Skip unknown arguments.
    arguments, _ = parser.parse_known_args()
    logger.info(
        "Parsed Parameters: show-gui: " + str(arguments.show_gui) +
        " catalogurl: " + str(arguments.catalogurl) +
        " workdir: " + arguments.workdir +
        " target-version: " + str(arguments.target_version) +
        " erase-install: " + str(arguments.erase_install) +
        " caching-server: " + str(arguments.caching_server))
    return arguments


def install_macos(arguments, script_thread):
    """Install macOS Installer Application and Launch startosinstall."""
    if arguments.erase_install == "ERASEINSTALL":
        logger.log(OLVL, "Checking for APFS volumes...")
        if not has_apfs():
            logger.log(FAIL, "This computer does not have an APFS volume. " +
                       "Please use a different method to wipe this machine.")
            script_thread.end_application()
        else:
            logger.log(OLVL, "APFS Present!")

    logger.log(OLVL, "Downloading list of latest macOS installers...")

    # Create an instance of the object that will hold all the data we need.
    installer = MakeInstaller(arguments, script_thread=script_thread)
    # Kick off the nested software_catalog instance object's parsing method.
    logger.log(OLVL, "Parsing list...")
    installer.software_catalog.start_parsing()

    script_thread.overall_progress(progress_percent(1))

    if not installer.software_catalog.product_info:
        logger.log(FAIL, "No macOS installer products found in the sucatalog.")
        time.sleep(30)
        sys.exit(1)

    # If no target version is selected, download the latest version of
    # macOS as determined by the version number.
    if arguments.target_version:
        arguments.target_version = arguments.target_version
        logger.info("Using parsed parameter: " + arguments.target_version)
    else:
        arguments.target_version = get_latest_macos_version(
            installer.software_catalog.product_info)
        logger.info("Using discovered version: " + arguments.target_version)

    # Let the installer know which product will be targeted.
    installer.target_version = matching_product_id(
        installer.software_catalog.product_info, arguments.target_version)
    logger.log(OLVL, "Found macOS Product ID: " + installer.target_version)

    # Use the product info to create a human-readable product name
    # i.e. "macOS Mojave 10.14 - Dated: 12-12-2018"
    version_string = parse_version_string(
        installer.software_catalog.product_info, installer.target_version)
    script_thread.version_text(version_string)

    script_thread.reset_stage_progress()
    logger.log(OLVL, "Downloading packages for: %s" % version_string)

    if not arguments.caching_server:
        logger.debug("Checking for caching server.")
        arguments.caching_server = discover_caching_server()

    logger.debug("Cahing Server: " + arguments.caching_server)

    # Download all the packages for the selected product.
    logger.debug("Replicating Selected Product.")
    installer.replicate_product()

    script_thread.show_spinner()

    logger.log(OLVL, "All Download Tasks Complete!")
    logger.log(OLVL, "Creating macOS installer in Applications folder...")

    # install the product to the Applications folder.
    installer.install_product()

    logger.log(
        OLVL, "Installer downloaded and staged in Applications folder...")
    script_thread.overall_progress(progress_percent(15))

    if arguments.installer_only:
        logger.log(OLVL, "Done!")
        script_thread.end_application()

    # Now we install macOS.
    installer.launch_osinstall()

    logger.info("Installation Complete! " +
                "Waiting for the installer to signal this script.")

    # Keep the script alive until it receives the signal from startosinstall.
    script_thread.wait_for_the_end()


def main():
    """Main Function. This will run when this script is called explicitly."""

    if os.getuid() != 0:
        logger.error("This script requires elevated privileges.")
        sys.exit(1)

    # Get the custom command line arguments passed to this script.
    arguments = get_arguments()

    if arguments.show_gui != "False":
        # Setup PyObjC references to GUI window
        # Prevent the Python icon from showing in the Dock.
        info = NSBundle.mainBundle().infoDictionary()
        info["LSUIElement"] = True
        info["NSRequiresAquaSystemAppearance"] = False
        app = NSApplication.sharedApplication()
        # NSApp.setDelegate_() doesn't retain a reference to the delegate
        # object, and will get picked up by garbage collection. A local
        # variable is enough to maintain that reference.
        delegate = AppDelegate.alloc().init()
        NSApp().setDelegate_(delegate)
        app.activateIgnoringOtherApps_(True)

        # Setup separate thread for underlying Python Script.
        script_thread = ScriptThread(arguments, gui=delegate.progress_window)
        script_thread.queue = delegate.progress_window.queue
        # Register the SIGUSR1 signal to the end_application method.
        signal.signal(signal.SIGUSR1, script_thread.receive_signal)

        # Create link between the script, the GUI, and logging.
        setup_logging(script_thread)
        # In this app we just start working, we don't have a stop/start button.
        script_thread.start_script()

        logger.debug("Starting main loop.")
        AppHelper.runEventLoop()
    else:
        script_thread = ScriptThread(arguments)
        script_thread.start_script()


if __name__ == "__main__":
    main()

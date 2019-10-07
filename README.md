# install_macos_gui
Installs macOS with a nice little GUI

#### This project owes its core functionality to Greg Neagle's https://github.com/munki/macadmin-scripts/blob/master/installinstallmacos.py

# Usage
```
installinstallmacos_gui.py -h
usage: installinstallmacos_gui.py [-h] [--show-gui SHOW_GUI]
                                  [--catalogurl CATALOGURL]
                                  [--workdir path_to_working_dir]
                                  [--target-version TARGET_VERSION]
                                  [--erase-install ERASE_INSTALL]
                                  [--caching-server CACHING_SERVER]
                                  [--installer-only INSTALLER_ONLY]

optional arguments:
  -h, --help            show this help message and exit
  --show-gui SHOW_GUI   Whether or not to show GUI to logged in user.
  --catalogurl CATALOGURL
                        Software Update catalog URL. This option overrides any
                        seedprogram option.
  --workdir path_to_working_dir
                        Path to working directory on a volume with over over
                        10G of available space. Defaults to current working
                        directory.
  --target-version TARGET_VERSION
                        Choose which version of macOS to target. The latest
                        version will be automatically selected.
  --erase-install ERASE_INSTALL
                        Choose whether or not to erase the disk when
                        installing macOS. Dangerous!
  --caching-server CACHING_SERVER
                        Specify a caching server (optional)
  --installer-only INSTALLER_ONLY
                        Only create the installer.
```

# Preview
```
$ installinstallmacos_gui.py --target=Catalina --installer-only=True
Password:
Parsed Parameters: show-gui: True catalogurl:  workdir: /private/tmp target-version: Catalina erase-install: False caching-server: None
Starting Script!
Downloading list of latest macOS installers...
Parsing list...
Using parsed parameter: Catalina
Found macOS Product ID: 061-18881
Downloading packages for: macOS Catalina 10.15 - Dated: 10-07-2019
```

![Dark Mode Interface](https://github.com/primalcurve/install_macos_gui/blob/master/images/dark_interface_catalina.png?raw=true)

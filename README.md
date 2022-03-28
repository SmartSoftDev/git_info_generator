# Introduction
Tools to use git information and automate CI/CD, packaging and release process.

# git_component tool (GC tool)
This tool can be used for several tasks during life cycle of a Project.
- It can reliable compute Version strings based on [semver](https://semver.org) and `git describe` approach. A released version will always be only in semver format. But intermediate versions (development versions) will be in `git describe` format.
- It can track git changes of a list of files or directories inside GIT repository. Additionally in can automatically compute the next semver version for the next release. This is useful in release automation pipelines.
- It can reliable detect if a list of commands should or not be executed based on the tracking changes of specific files. The decision to run or not the commands can be computed based on the new version string. This is specially useful when deciding to redeploy the project or not. Or the run or not decision can be computed based on changes from a common ancestor commit (for example comparing it to origin/master commit). This is specially useful in CI/CD pipelines, where commands can be executed depending if there are changes compared to origin/master reference.
- It offers a robust mechanism to package the project and keep single point of truth about project files. Since the project files are listed (for the change tracking), packaging action knows all the information to easily create a *.deb, .tar.gz or .zip package with the project
- It can create precise changelog entries based on git history, for each version or deployment. Since the project files are listed (for the change tracking), a precise changelog from the git history can be computed. This filters only the commits relevant to this particular project.
- The generated changelog contains statistical information and advances metrics about the Project's code. The metrics can be used to determine how big the changes are and if features or test cases are affected in this version.

Below each functionality will be explained in details.

## GC Tool configuration file

GC Tool is reading a Yaml file for it's configuration: `.git_component.yml`. One GIT repo may contain multiple configuration files
in different directories or even in the same directory.
The only mandatory field in that file is "name" which identifies the component from others.

Depending on the features other configuration fields can be added.

## Git changes tracking

In order to track changes from git history each project should list all files or directories that are affecting this project.
In such a way the GC tool can read the git history and decide wether it is affecting the project or not.
To configure the paths to the tracked files "location" field should be used like that:
```
location:
  - path/to/tracked/file
  - path/to/tracked/directory
```

All the paths are relative to `location_root` which by default is set to the path of configuration file. `location_root` can be set in configuration file like:
```
location_root: relativeToDefaultValue/or/absolute/path
```



The app receives a list of paths (or a yaml file with path list) and then gets the git hash of those locations and at
the end it computes one hash from the one's from git and returns it.
NOTE: Git returns the hash FROM committed changes not for stashed once! so make sure when running
git_component_hash that you do not have local changes in the git repositories.

To ease automation the app will look to .git_component.yml file in current directory.

config file format:
name: AppName
git_tag_prefix: tag prefix to look for latest version, default ""
location_root:  from where to start to copy locations
locations:
  - relative/path/directory1
  - relative/path2/file1
package-storage: path to the directory to store newly generated packages (relative or absolute)
package-archive-type: tgz or zip
package-info: a json object written to the package info.json file
package-actions:
  install: path_to_install_script
  update: path_to_update_script
  uninstall: path_uninstall_script
  other_action: path_to_other_action

# Action lists ca be defined as simple lists with Bash commands or as object with following content:
action-list-name:
  depends:
    - name-of-other-action-lists
  git_files:
    - paths_for_files_to_monitor_changes (relative to location_root)
  run
    - bash_commands_list

# for example
install-scripts: # list of scripts to run when the component needs installation
  - bash commands
update-script:  # list of scripts to run when the component needs update
  - bash commands
update-dependencies-scripts:  # list of scripts to run when the component needs update
  run_on_change:
    - be/requirement.pep3
    - fe_ui/package.json
    - fe_prm/package.json
  run:
    - bash commands


NOTE: if you have ideas how to improve this script just create an issue on https://github.com/SmartSoftDev/GBashLib

# Run commands examples:

git_component run_on_change -C update-scripts unittes-scripts ...
git_component run_on_change -C update-dependencies-scripts
git_component get_changelog -o destination_file.yml

# useful find last version of deb file
find . -type f -name 'crm_*.deb' | sort -r -V  | head -n1

# Packaging

Packaging should solve following challenges:

* granularity, change-detection. In the repo, the component can use a subset of repo's files and the changes will be detected accordingly.
* versioning: TAG_VERSION.BUILD-COMMIT_HASH multiple components might be bound to a specific version of other components from the same project. In the same time the components can be installed on different machines and have to be independent.
  * TAG_VERSION comes from git tags (with configurable git tag prefixes (multiple prefixes)).
  * BUILD comes from the number of changes since last tag, if BUILD > 0 then -COMMIT_HASH is added.
  * when there are no tags yet TAG_VERSION=0.0.1
  * forcing version should be possible ( for example: for SW update FAKE future version )
* dependency:
  * system:
    * required packages (apt, since it runs in locking), + prepare scripts
    * or pre-prepared system virtual-environments (docker, VM's, WLS's).
  * other package managers (pip, npm, ...) and their virtual-environments.
  * local dependency on other git_components  (BE's need FE's, in order to function)
* packaging using popular package managers: deb (apt), rpm, zip, ...
  - Create a temporary directory with following structure:
    - src
    - cfg: systemd templates, other templates
    - scripts: install.sh, uninstall.sh, update.sh
    - info.json  # all necessary info and dependencies.
  - After we can package the directory into TGZ, RPM, DEB, ZIP, etc.

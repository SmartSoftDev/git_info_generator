# git_info_genarator
Tools to use git information and automate release and deployment process.

# Packaging

Packaging should solve following challenges:

* granularity, change-detection. In the repo, the component can use a subset of repo's files and the changes will be detected acordingly.
* versioning: TAG_VERSION.BUILD-COMMIT_HASH multiple components might be bound to a specific version of other components from the same project. In the same time the components can be installed on different machines and have to be independent.
  * TAG_VERSION comes from git tags (with configurable git tag prefixes (multiple prefixes)).
  * BUILD comes from the number of changes since last tag, if BUILD > 0 then -COMMIT_HASH is added.
  * when there no tags yet TAG_VERSION=0.0.1
  * forcing version should be possible ( for example: for SW update FAKE future version )
* dependency:
  * system:
    * required packages (apt, since it runs in locking), + prepare scripts
    * or pre-prepared system virtual-environments (docker, VM's, WLS's).
  * other package managers (pip, npm, ...) and their virtual-environments.
  * local dependency on other git_components  (BE's need FE's, in order to funciton)
* packaging using popular package managers: deb (apt), rpm, zip, ...
  - Create a temporary directory with followign structure:
    - src
    - cfg: systemd templates, other templates
    - scripts: install.sh, uninstall.sh, update.sh
    - info.json  # all necesarry info and dependecies.
  - After we can pacakge the directory into TGZ, RPM, DEB, ZIP, etc.

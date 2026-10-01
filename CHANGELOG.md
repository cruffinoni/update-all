# Changelog

All notable changes to this project will be documented in this file.

## [2.0.10] - 2026-10-01

### Added
- Version bump to 2.0.10

### Fixed
- Fix Python traceback during sudo verification on macOS: when a fresh PTY cannot become the controlling terminal (`TIOCSCTTY` EPERM), the bootstrap now reports it to the parent, which retries on a different PTY instead of streaming the error.


## [2.0.9] - 2026-09-27

### Added
- Version bump to 2.0.9


## [2.0.8] - 2026-09-24

### Added
- Version bump to 2.0.8


## [2.0.7] - 2026-09-20

### Added
- Version bump to 2.0.7


### Fixed
- Fix sudo password retries reported on Ubuntu 26.04.1 LTS: request a fresh password after "Authentication failed, try again." instead of reusing the rejected credential.

## [2.0.6] - 2026-09-14

### Added
- Version bump to 2.0.6


## [2.0.2] - 2026-07-21

### Added
- Version bump to 2.0.2


## [2.0.1] - 2026-07-21

### Added
- Version bump to 2.0.1


## [2.0.0] - 2026-07-19

### Added
- Version bump to 2.0.0

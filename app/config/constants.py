"""Application metadata and directory/file naming constants.

Anything a deployment might reasonably want to change lives in
``app.config.settings`` and is overridable from ``config.json``. Only genuinely
fixed identifiers belong here.
"""

APP_NAME = "MedFlow"
APP_SLUG = "medflow"
APP_TAGLINE = "Patient Management System"
APP_DESCRIPTION = "Native desktop patient management system"

#: Name of the JSON configuration file looked for beside the application.
CONFIG_FILENAME = "config.json"

#: Environment variable that overrides the configuration file location.
CONFIG_ENV_VAR = "MEDFLOW_CONFIG"

#: Sub-directories created beneath the application base directory.
DATA_DIRNAME = "data"
BACKUP_DIRNAME = "backups"
EXPORT_DIRNAME = "exports"
LOG_DIRNAME = "logs"

DATABASE_FILENAME = "medflow.db"
LOG_FILENAME = "medflow.log"

#: Storage modes. Only ``local`` is implemented; ``network`` is reserved so the
#: setting can be written to disk before the API layer exists.
STORAGE_MODE_LOCAL = "local"
STORAGE_MODE_NETWORK = "network"

#: Actor recorded on changes made by the application itself rather than a person.
SYSTEM_ACTOR = "system"

#: Appearance modes accepted by CustomTkinter.
APPEARANCE_MODES = ("System", "Light", "Dark")

#: Supported export formats, mapped to file extensions.
EXPORT_FORMATS = {"csv": ".csv", "json": ".json"}

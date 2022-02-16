import coloredlogs, logging, os

if not os.getenv('OOO_DO_NOT_REINSTALL_COLORED_LOGS'):
    coloredlogs.install(level=os.getenv('LOG_LEVEL', 'INFO'))


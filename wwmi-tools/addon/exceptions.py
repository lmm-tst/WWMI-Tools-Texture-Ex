class ConfigError(Exception):
    def __init__(self, cfg, setting_name, error_message):
        cfg.last_error_setting_name = setting_name
        cfg.last_error_text = error_message
        print('ERROR:', error_message)
        super().__init__(error_message)


def clear_error(cfg):
    cfg.last_error_setting_name = ''
    cfg.last_error_text = ''

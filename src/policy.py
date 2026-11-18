"""One definition of the four local screening rules and their legacy flags."""

ACTION_FIELDS = {
    "check1": "action_check1",
    "check2": "action_check2",
    "check3": "action_check3",
    "block_code": "action_code",
}
ACTIONS = ("allow", "warn", "redact", "block")
DEFAULT_FLAGS = {flag: int(flag != "block_code") for flag in ACTION_FIELDS}


def legacy_action(enabled):
    return "block" if enabled else "allow"


def rule_actions(values):
    """Resolve each rule, including callers that only supply legacy booleans."""
    result = {}
    for flag, field in ACTION_FIELDS.items():
        try:
            result[flag] = values[field]
        except (KeyError, IndexError):  # mappings and sqlite3.Row
            try:
                enabled = values[flag]
            except (KeyError, IndexError):
                enabled = DEFAULT_FLAGS[flag]
            result[flag] = legacy_action(enabled)
    return result


def action_settings(values):
    return {ACTION_FIELDS[flag]: action for flag, action in rule_actions(values).items()}


def redaction_only(values):
    """An override can release a block, but cannot release a redact rule."""
    return {ACTION_FIELDS[flag]: "redact" if action == "redact" else "allow"
            for flag, action in rule_actions(values).items()}

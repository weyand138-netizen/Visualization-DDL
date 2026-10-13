"""Resolve an authorized QQ sender to exactly one independent workspace."""
import re


def account_for_qq(sender, allowed, bindings):
    sender = str(sender)
    if sender not in {str(item) for item in allowed}:
        return None
    if not bindings:
        return "admin"  # Preserve existing single-account plugin configurations.
    matches = []
    for binding in bindings:
        if not isinstance(binding, str):
            continue
        qq, separator, account = binding.partition(":")
        if separator and qq.strip() == sender:
            matches.append(account.strip())
    if len(matches) != 1 or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", matches[0]):
        return None
    return matches[0]

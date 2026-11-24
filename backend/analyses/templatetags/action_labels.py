from django import template

from analyses.habits import ACTION_NAMES, behavior_name

register = template.Library()
register.filter("behavior_name", behavior_name)


@register.filter
def action_name(label):
    return ACTION_NAMES.get(label, label)


@register.simple_tag
def action_names():
    return ACTION_NAMES

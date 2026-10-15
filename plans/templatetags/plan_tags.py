from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """ดึงค่าจาก dictionary ด้วย key - ใช้ใน template: dict|get_item:key"""
    if dictionary is None:
        return []
    return dictionary.get(key, [])

@register.filter
def get_attr(obj, attr_name):
    """ดึง attribute จาก object - ใช้ใน template: obj|get_attr:'field_name'"""
    return getattr(obj, attr_name, False)

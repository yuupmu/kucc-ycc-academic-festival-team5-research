"""Schema helpers for constrained model responses."""
import json


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def array(item, least, most):
    return dict(type='array', items=item, minItems=least, maxItems=most)


def matches(value, spec):
    """Validate the same small schema used for constrained decoding, including truncated responses."""
    if 'oneOf' in spec:
        return sum(matches(value, s) for s in spec['oneOf']) == 1
    kind = spec['type']
    if kind == 'object':
        props = spec['properties']
        return type(value) is dict and value.keys() == props.keys() and all(matches(value[k], v) for k,v in props.items())
    if kind == 'array':
        return (type(value) is list and spec['minItems'] <= len(value) <= spec['maxItems']
                and all(matches(item, spec['items']) for item in value))
    if kind == 'integer':
        return (type(value) is int and spec.get('minimum', value) <= value <= spec.get('maximum', value))
    if kind == 'boolean':
        return type(value) is bool
    return (kind == 'string' and type(value) is str and len(value) <= spec.get('maxLength', len(value))
            and ('enum' not in spec or value in spec['enum']))


def decode(text, schema):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if matches(value, schema) else None

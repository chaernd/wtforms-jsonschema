import copy
from collections import OrderedDict

import six
import wtforms
from wtforms.fields import html5


def pretty_name(name):
    """Converts 'first_name' to 'First name'"""
    if not name:
        return u''
    return name.replace('_', ' ').capitalize()


_DEFAULT_CONVERSIONS = {}
_INPUT_TYPE_MAP = {}
try:
    import wtforms_components

    _DEFAULT_CONVERSIONS[wtforms_components.ColorField] = {
        'type': 'string',
        'format': 'color',
        'form': {
            'type': 'color',
        },
    }

    # TODO min/max
    _DEFAULT_CONVERSIONS[wtforms_components.DecimalRangeField] = {
        'type': 'number',
    }
    _DEFAULT_CONVERSIONS[wtforms_components.IntegerRangeField] = {
        'type': 'integer',
    }
    _INPUT_TYPE_MAP['color'] = wtforms_components.ColorField

except ImportError:
    pass


class WTFormToJSONSchema(object):

    DEFAULT_CONVERSIONS = OrderedDict([
        (html5.URLField, {
            'type': 'string',
            'format': 'uri',
            'form': {
                'type': 'url',
            },
        }),
        (wtforms.fields.FileField, {
            'type': 'string',
            'format': 'uri',
            'form': {
                'type': 'file',
            },
        }),
        (wtforms.fields.DateField, {
            'type': 'string',
            'format': 'date',
            'form': {
                'type': 'date',
            },
        }),
        (wtforms.fields.DateTimeField, {
            'type': 'string',
            'format': 'datetime',
            'form': {
                'type': 'datetime',
            },
        }),
        (wtforms.fields.DecimalField, {
            'type': 'number',
            'form': {
                'type': 'number',
                'step': 'any',
            },
        }),
        (wtforms.fields.IntegerField, {
            'type': 'integer',
            'form': {
                'type': 'number',
                'min': '1',
                'step': '1',
            },
        }),
        (wtforms.fields.BooleanField, {
            'type': 'boolean',
            'form': {},
        }),
        (wtforms.fields.PasswordField, {
            'type': 'string',
            'form': {
                'type': 'password',
            },
        }),
        (html5.SearchField, {
            'type': 'string',
            'form': {
                'type': 'search',
            },
        }),
        (html5.TelField, {
            'type': 'string',
            'format': 'phone',
            'form': {
                'type': 'tel',
            },
        }),
        (html5.EmailField, {
            'type': 'string',
            'format': 'email',
            'form': {
                'type': 'email',
            },
        }),
        (html5.DateTimeLocalField, {
            'type': 'string',
            'format': 'datetime',
            'form': {
                'type': 'datetime-local',
            },
        }),
        (wtforms.fields.StringField, {
            'type': 'string',
            'form': {
                'type': 'text',
            },
        }),
    ])

    INPUT_TYPE_MAP = {
        'text': wtforms.fields.StringField,
        'password': wtforms.fields.PasswordField,
        'checkbox': wtforms.fields.BooleanField,
        'tel': html5.TelField,
    }

    def __init__(self, conversions=None, include_array_item_titles=True,
                 include_array_title=True):
        self.conversions = conversions or self.DEFAULT_CONVERSIONS
        self.include_array_item_titles = include_array_item_titles
        self.include_array_title = include_array_title

    def convert_form(self, form, json_schema=None, forms_seen=None, path=None):
        forms_seen = forms_seen or dict()
        path = path or []
        json_schema = json_schema or {
            'type': 'object',
            'schema': {
                'properties': OrderedDict(),
            },
            'form': [],
        }
        key = id(form)
        if key in forms_seen:
            json_schema['$ref'] = '#'+'/'.join(forms_seen[key])
            json_schema.pop('properties', None)
            return json_schema
        forms_seen[key] = path
        # _unbound_fields preserves order, _fields does not
        if hasattr(form, '_unbound_fields'):
            if form._unbound_fields is None:
                form = form()
            fields = [name for name, ufield in form._unbound_fields]
        else:
            fields = form._fields.keys()
        for name in fields:
            if name not in form._fields:
                continue
            field = form._fields[name]
            json_schema['schema']['properties'][name], form_obj = (
                self.convert_formfield(name, field, json_schema,
                                       forms_seen, path))
            if form_obj is None:
                form_obj = {'key': name}
            else:
                form_obj['key'] = name
            json_schema['form'].append(form_obj)

        return json_schema

    def _find_conversion_class(self, cls):
        if self.conversions.get(cls):
            return cls
        else:
            for klass in six.iterkeys(self.conversions):
                if issubclass(cls, klass):
                    return klass
            raise KeyError(cls)

    def _find_conversion(self, field, name):
        cls = field.__class__
        try:
            klass = self._find_conversion_class(cls)
            return copy.deepcopy(self.conversions.get(klass))
        except (KeyError, TypeError) as exc:
            niexc = NotImplementedError(
                'Unsupported field {name}: {field!r}'.format(
                    name=name, field=field))
            six.raise_from(niexc, exc)

    def convert_formfield(self, name, field, json_schema, forms_seen, path):
        widget = field.widget
        path = path + [name]
        target_def = {
            'title': field.label.text,
            'description': field.description,
        }
        if field.flags.required:
            target_def['required'] = True
            json_schema.setdefault('required', [])
            json_schema['required'].append(name)
        if hasattr(self, 'convert_%s' % field.__class__.__name__):
            func = getattr(self, 'convert_%s' % field.__class__.__name__)
            return func(name, field, json_schema)

        params = self._find_conversion(field, name)

        form = params.pop('form', None)
        target_def.update(params)

        if isinstance(field, wtforms.fields.FormField):
            key = id(field.form_class)
            if key in forms_seen:
                return {"$ref": "#"+"/".join(forms_seen[key])}
            forms_seen[key] = path
            target_def.update(self.convert_form(field.form_class(obj=getattr(field, '_obj', None)), None, forms_seen, path))
        elif isinstance(field, wtforms.fields.FieldList):
            if not self.include_array_title:
                target_def.pop('title')
                target_def.pop('description')
            target_def['type'] = 'array'
            subfield = field.unbound_field.bind(getattr(field, '_obj', None), name)
            target_def['items'] = self.convert_formfield(name, subfield, json_schema, forms_seen, path)
            if not self.include_array_item_titles:
                target_def['items'].pop('title', None)
                target_def['items'].pop('description', None)
        elif hasattr(widget, 'input_type'):
            it = self.INPUT_TYPE_MAP.get(widget.input_type, wtforms.fields.StringField)
            if hasattr(self, 'convert_%s' % it):
                return getattr(self, 'convert_%s' % it)(name, field, json_schema)
            target_def.update(self.conversions[it])
        else:
            target_def['type'] = 'string'
        return target_def, form

    def convert_SelectField(self, name, field, json_schema):
        values = list()
        for val, label in field.choices:
            if isinstance(label, (list, tuple)):  # wonky option groups
                values.extend([x for x, y in label])
            else:
                values.append(val)

        target_def = {
            'title': field.label.text,
            'description': field.description,
            'enum': values,
            'ux-widget-choices': list(field.choices),
        }
        if field.flags.required:
            target_def['required'] = True
        return target_def

    def convert_RadioField(self, name, field, json_schema):
        target_def = {
            'title': field.label.text,
            'description': field.description,
            'enum': [x for x, y in field.choices],
            'ux-widget': 'radio',
            'ux-widget-choices': list(field.choices),
        }
        if field.flags.required:
            target_def['required'] = True
        return target_def


WTFormToJSONSchema.DEFAULT_CONVERSIONS.update(_DEFAULT_CONVERSIONS)
WTFormToJSONSchema.INPUT_TYPE_MAP.update(_INPUT_TYPE_MAP)

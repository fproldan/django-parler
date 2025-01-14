"""
Custom generic managers
"""
import django
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.query import QuerySet
from django.utils.translation import get_language

from parler import appsettings
from parler.utils import get_active_language_choices


class TranslatableQuerySet(QuerySet):
    """
    An enhancement of the QuerySet which sets the objects language before they are returned.

    When using this class in combination with *django-polymorphic*, make sure this
    class is first in the chain of inherited classes.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._language = None

    def _clone(self):
        c = super()._clone()
        c._language = self._language
        return c

    def create(self, **kwargs):
        # Pass language setting to the object, as people start assuming things
        # like .language('xx').create(..) which is a nice API after all.
        if self._language:
            kwargs["_current_language"] = self._language
        return super().create(**kwargs)

    def load_translations(self, instance):
        """
        Load translatable fields of an instance.

        Args:
            instance: The instance to load the translations for.
        """
        from parler.models import TranslatableModel
        if not isinstance(instance, TranslatableModel):
            return

        for field in instance._parler_meta.get_all_fields():
            getattr(instance, field)

    def _fetch_all(self):
        # Make sure the current language is assigned when Django fetches the data.
        # This low-level method is overwritten as that works better across Django versions.
        # Alternatives includes hacking the _iterable_class, which breaks django-polymorphic
        super()._fetch_all()
        if (
            self._language is not None
            and self._result_cache
            and isinstance(self._result_cache[0], models.Model)
        ):
            for obj in self._result_cache:
                self.load_translations(obj)
                obj.set_current_language(self._language)

    def _extract_model_params(self, defaults, **kwargs):
        # default implementation in Django>=1.11 doesn't allow non-field attributes,
        # so process them manually
        translated_defaults = {}
        if defaults:
            for field in self.model._parler_meta.get_all_fields():
                try:
                    translated_defaults[field] = defaults.pop(field)
                except KeyError:
                    pass

        params = super()._extract_model_params(defaults, **kwargs)
        params.update(translated_defaults)
        return params

    def language(self, language_code=None):
        """
        Set the language code to assign to objects retrieved using this QuerySet.
        """
        from django.utils import translation
        if language_code is None:
            language_code = translation.get_language() or appsettings.PARLER_LANGUAGES.get_default_language()

        self._language = language_code
        return self

    def translated(self, *language_codes, **translated_fields):
        """
        Only return translated objects which of the given languages.

        When no language codes are given, only the currently active language is returned.

        .. note::

            Due to Django `ORM limitations <https://docs.djangoproject.com/en/dev/topics/db/queries/#spanning-multi-valued-relationships>`_,
            this method can't be combined with other filters that access the translated fields. As such, query the fields in one filter:

            .. code-block:: python

                qs.translated('en', name="Cheese Omelette")

            This will query the translated model for the ``name`` field.
        """
        relname = self.model._parler_meta.root_rel_name

        if not language_codes:
            language_codes = (get_language(),)

        filters = {}
        for field_name, val in translated_fields.items():
            if field_name.startswith("master__"):
                filters[field_name[8:]] = val  # avoid translations__master__ back and forth
            else:
                filters[f"{relname}__{field_name}"] = val

        if len(language_codes) == 1:
            filters[relname + "__language_code"] = language_codes[0]
            return self.filter(**filters)
        else:
            filters[relname + "__language_code__in"] = language_codes
            return self.filter(**filters).distinct()

    def active_translations(self, language_code=None, **translated_fields):
        """
        Only return objects which are translated, or have a fallback that should be displayed.

        Typically that's the currently active language and fallback language.
        This should be combined with ``.distinct()``.

        When ``hide_untranslated = True``, only the currently active language will be returned.
        """
        # Default:     (language, fallback) when hide_translated == False
        # Alternative: (language,)          when hide_untranslated == True
        language_codes = get_active_language_choices(language_code)
        return self.translated(*language_codes, **translated_fields)


class TranslatableManager(models.Manager.from_queryset(TranslatableQuerySet)):
    """
    The manager class which ensures the enhanced TranslatableQuerySet object is used.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if not isinstance(qs, TranslatableQuerySet):
            raise ImproperlyConfigured(
                f"{self.__class__.__name__}._queryset_class does not inherit from TranslatableQuerySet"
            )
        return qs


# Export the names in django-hvad style too:
TranslationQueryset = TranslatableQuerySet
TranslationManager = TranslatableManager

from app.services.i18n_service import (
    SUPPORTED_LOCALES,
    marketing_path,
    translate,
)
import app.services.i18n_service as mod

assert translate("Guardar", locale="en") == "Save", translate("Guardar", locale="en")
assert translate("Cancelar", locale="fr") == "Annuler"
assert marketing_path("/alta", "en") == "/en/alta"
assert marketing_path("/", "pt") == "/pt/"
assert "en" in SUPPORTED_LOCALES
assert not hasattr(mod, "translate_html_document")
print("OK", SUPPORTED_LOCALES)

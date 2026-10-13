import time

from app.services.contact_spam_service import looks_like_spam, new_form_ts


def test_telegra_ph_rolls_royce_es_spam():
    assert looks_like_spam(
        nombre='EdwardRew',
        email='gettulu@gmail.com',
        mensaje=(
            'GRAB A 2026 ROLLS-ROYCE PHANTOM FOR $15,000 TODAY '
            'https://telegra.ph/How-to-get-a-new-2026-Rolls-Royce-Phantom-for-just-15000-Message-ID-440421-09-28'
        ),
        form_ts=str(time.time() - 10),
    )


def test_earn_millions_telegra_es_spam():
    assert looks_like_spam(
        nombre='SpamBot',
        email='x@y.com',
        mensaje=(
            'The guide to read the news and earn $50,000,000 per month '
            'https://telegra.ph/Read-the-latest-news-and-earn-50000000-in-a-month-Message-ID-469792-10-05'
        ),
        form_ts=str(time.time() - 10),
    )


def test_contacto_legitimo_no_es_spam():
    assert not looks_like_spam(
        nombre='Juan Pérez',
        email='juan@constructora.es',
        empresa='Constructora Pérez SL',
        mensaje='Hola, nos interesa SignaPlan para gestionar obras y certificaciones. ¿Podemos hablar?',
        form_ts=str(time.time() - 8),
    )


def test_una_url_normal_sin_ganchos_no_es_spam():
    assert not looks_like_spam(
        nombre='María López',
        email='maria@empresa.com',
        mensaje='Somos https://empresa.com y queremos una demo del portal de subcontratas.',
        form_ts=str(time.time() - 5),
    )


def test_envio_instantaneo_es_spam():
    assert looks_like_spam(
        nombre='Juan Pérez',
        email='juan@constructora.es',
        mensaje='Hola, nos interesa una demo del producto para nuestra empresa.',
        form_ts=str(time.time()),
    )


def test_form_ts_invalido_es_spam():
    assert looks_like_spam(
        nombre='Juan Pérez',
        email='juan@constructora.es',
        mensaje='Hola, nos interesa una demo del producto para nuestra empresa.',
        form_ts='nope',
    )


def test_new_form_ts_es_numero():
    float(new_form_ts())

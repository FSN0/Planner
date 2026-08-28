# tests/integration/test_marketing_seo.py
#
# Canónicas en apex, sitemap/robots y noindex del conmutador de idioma.
# El 301 www → signaplan.com lo hace Caddy; Flask sigue respondiendo 200.

from app.services.seo_origin_service import marketing_origin, marketing_url


MKT = {'Host': 'signaplan.com'}
WWW = {'Host': 'www.signaplan.com'}


class TestMarketingOrigin:

    def test_apex_y_www_usan_origen_canonico(self, app):
        with app.test_request_context('/', headers=WWW):
            assert marketing_origin() == 'https://signaplan.com'
            assert marketing_url('/recursos/') == 'https://signaplan.com/recursos/'

    def test_localhost_sigue_el_host_de_la_peticion(self, app):
        with app.test_request_context('/', headers={'Host': 'localhost'}):
            origin = marketing_origin()
            assert origin.startswith('http://localhost')
            assert 'signaplan.com' not in origin


class TestCanonicalHead:

    def test_home_www_canonica_es_apex(self, client):
        html = client.get('/', headers=WWW).get_data(as_text=True)
        assert 'rel="canonical" href="https://signaplan.com/"' in html
        assert 'href="https://www.signaplan.com/"' not in html

    def test_aviso_legal_tiene_canonica(self, client):
        resp = client.get('/legal/aviso-legal', headers=MKT)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'rel="canonical" href="https://signaplan.com/legal/aviso-legal"' in html

    def test_software_constructoras_titulo_sin_erp(self, client):
        html = client.get(
            '/recursos/software-constructoras', headers=MKT
        ).get_data(as_text=True)
        assert 'sin montar un ERP' in html or 'sin ERP' in html or 'no un ERP' in html
        assert 'rel="canonical" href="https://signaplan.com/recursos/software-constructoras"' in html


class TestSitemapRobots:

    def test_sitemap_locs_en_apex(self, client):
        resp = client.get('/sitemap.xml', headers=WWW)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '<loc>https://signaplan.com/</loc>' in body
        assert '<loc>https://signaplan.com/recursos/planificador-de-obra</loc>' in body
        assert 'www.signaplan.com' not in body

    def test_sitemap_incluye_guias_nuevas(self, client):
        body = client.get('/sitemap.xml', headers=MKT).get_data(as_text=True)
        assert '<loc>https://signaplan.com/recursos/cuadrante-personal-obra</loc>' in body
        assert '<loc>https://signaplan.com/recursos/inspeccion-trabajo-construccion</loc>' in body
        assert '<loc>https://signaplan.com/recursos/erp-constructoras-gratis</loc>' in body
        assert '<loc>https://signaplan.com/recursos/software-gestion-empresa-constructora</loc>' in body
        assert '<loc>https://signaplan.com/recursos/programa-para-constructoras</loc>' in body
        assert '<lastmod>2026-08-16</lastmod>' in body

    def test_aviso_y_condiciones_no_comparten_meta_description(self, client):
        aviso = client.get('/legal/aviso-legal', headers=MKT).get_data(as_text=True)
        cond = client.get('/legal/condiciones', headers=MKT).get_data(as_text=True)
        assert 'titular del sitio' in aviso.lower() or 'Aviso legal de SignaPlan' in aviso
        assert 'Condiciones de uso de SignaPlan' in cond
        assert 'name="description" content="Aviso legal de SignaPlan' in aviso
        assert 'name="description" content="Condiciones de uso de SignaPlan' in cond

    def test_erp_gratis_y_programa_constructoras(self, client):
        erp = client.get('/recursos/erp-constructoras-gratis', headers=MKT)
        assert erp.status_code == 200
        html = erp.get_data(as_text=True)
        assert 'ERP para constructoras gratis' in html
        assert 'rel="canonical" href="https://signaplan.com/recursos/erp-constructoras-gratis"' in html
        prog = client.get('/recursos/programa-para-constructoras', headers=MKT)
        assert prog.status_code == 200
        assert 'programa para constructoras' in prog.get_data(as_text=True).lower()

    def test_home_enlaza_guias_y_title_cuadrante(self, client):
        html = client.get('/', headers=MKT).get_data(as_text=True)
        assert 'Cuadrante, fichaje y flota para constructoras' in html
        assert '/recursos/cuadrante-personal-obra' in html
        assert '/recursos/inspeccion-trabajo-construccion' in html
        assert '/recursos/erp-constructoras-gratis' in html
        assert 'Soltec' not in html

    def test_robots_bloquea_preferencias_y_apunta_sitemap_apex(self, client):
        body = client.get('/robots.txt', headers=MKT).get_data(as_text=True)
        assert 'Disallow: /preferencias/' in body
        assert 'Sitemap: https://signaplan.com/sitemap.xml' in body


class TestGuiasConvertibles:

    def test_cuadrante_no_es_gantt(self, client):
        resp = client.get('/recursos/cuadrante-personal-obra', headers=MKT)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'cuadrante de personal de obra' in html.lower()
        assert 'no es un Gantt' in html or 'No es un planificador de obra tipo Gantt' in html
        assert 'rel="canonical" href="https://signaplan.com/recursos/cuadrante-personal-obra"' in html
        assert '/alta' in html

    def test_inspeccion_obra(self, client):
        resp = client.get('/recursos/inspeccion-trabajo-construccion', headers=MKT)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'inspección' in html.lower()
        assert 'rel="canonical" href="https://signaplan.com/recursos/inspeccion-trabajo-construccion"' in html
        assert '/alta' in html

    def test_home_enlaza_guias_y_title_cuadrante(self, client):
        html = client.get('/', headers=MKT).get_data(as_text=True)
        assert 'Cuadrante, fichaje y flota para constructoras' in html
        assert '/recursos/cuadrante-personal-obra' in html
        assert '/recursos/inspeccion-trabajo-construccion' in html
        assert 'Soltec' not in html

    def test_software_constructoras_cta_alta(self, client):
        html = client.get(
            '/recursos/software-constructoras', headers=MKT
        ).get_data(as_text=True)
        assert 'no un ERP' in html or 'sin montar un ERP' in html
        assert '/alta' in html


class TestLocaleNoindex:

    def test_cambio_idioma_noindex(self, client):
        resp = client.get(
            '/preferencias/idioma',
            query_string={'lang': 'fr', 'next': '/'},
            headers=MKT,
        )
        assert resp.status_code in (301, 302)
        assert resp.headers.get('X-Robots-Tag') == 'noindex, nofollow'

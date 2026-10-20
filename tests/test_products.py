"""Tests for the Products (Garimpo) scouting, AI dossier, affiliate links, and Studio API."""

import io
import json
import time

from purffle_shorts import products as PR
from purffle_shorts import studio as ST
from purffle_shorts.history import History
from purffle_shorts.pipeline import final_description
from purffle_shorts.script import Scene, Script, review_prompt


class FakeResp:
    def __init__(self, text="", status=200, json_data=None):
        self.text = text
        self.status_code = status
        self._json = json_data

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTP:
    def __init__(self, handler):
        self.handler = handler

    def get(self, url, **kwargs):
        return self.handler(url, **kwargs)


class FakeLLM:
    name = "fake"

    def generate_json(self, prompt, system=""):
        return {
            "products": [
                {
                    "index": 0,
                    "viral_score": 92,
                    "short_name": "Seladora a Vácuo",
                    "pain_point": "Comida estragando rápido na geladeira",
                    "hook_idea": "Sua comida estraga em 3 dias por causa disso!",
                    "visual_angle": "Fechando saco plástico e sugando o ar em 3 segundos",
                    "benefits": ["Conserva 5x mais", "Portátil USB", "Corta e sela"],
                }
            ]
        }


def test_detect_platform():
    assert PR.detect_platform("https://inspireuplift.com/products/vacuum") == "shopify"
    assert PR.detect_platform("https://loja.mitiendanube.com/produtos/x") == "nuvemshop"
    assert PR.detect_platform("https://site.com", '<script src="https://cdn.shopify.com/s/files.js"></script>') == "shopify"
    assert PR.detect_platform("https://site.com", "var LS = { store: 'tiendanube' };") == "nuvemshop"
    assert PR.detect_platform("https://site.com", '<link href="/wp-content/plugins/woocommerce/style.css">') == "woocommerce"


def test_scout_shopify_store_and_ai_dossier(monkeypatch):
    shopify_payload = {
        "products": [
            {
                "title": "Mini Seladora Portátil a Vácuo 2 em 1 USB",
                "handle": "mini-seladora-vacuo",
                "vendor": "Casa Tech",
                "product_type": "Cozinha",
                "body_html": "<p>Conserva alimentos até 5x mais tempo. Bateria recarregável USB.</p>",
                "variants": [{"price": "79.90", "compare_at_price": "159.90"}],
                "images": [{"src": "https://cdn.shopify.com/s/files/1/seladora1.jpg"}],
                "media": [
                    {
                        "media_type": "video",
                        "sources": [{"url": "https://cdn.shopify.com/videos/seladora.mp4", "format": "mp4"}],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(PR, "http", lambda: FakeHTTP(lambda url, **kw: FakeResp(json_data=shopify_payload)))
    items = PR.scout_shopify_store("https://minhaloja.com", limit=5)
    assert len(items) == 1
    p = items[0]
    assert p["platform"] == "shopify"
    assert p["best_seller_rank"] == 1
    assert p["discount_pct"] == 50
    assert p["images"] == ["https://cdn.shopify.com/s/files/1/seladora1.jpg"]
    assert p["videos"] == ["https://cdn.shopify.com/videos/seladora.mp4"]

    enriched = PR.analyze_products_with_ai(FakeLLM(), items, language="pt")
    assert enriched[0]["viral_score"] == 92
    assert enriched[0]["short_name"] == "Seladora a Vácuo"
    assert "geladeira" in enriched[0]["pain_point"]
    assert enriched[0]["benefits"] == ["Conserva 5x mais", "Portátil USB", "Corta e sela"]


def test_scout_woocommerce_store_api(monkeypatch):
    wc_payload = [
        {
            "name": "Escova Elétrica Giratória 7 em 1",
            "permalink": "https://wooloja.com.br/produto/escova-eletrica/",
            "short_description": "<p>Limpa banheiro e azulejos sem esforço nas costas.</p>",
            "prices": {
                "price": "12990",
                "regular_price": "19990",
                "currency_minor_unit": 2,
                "currency_prefix": "R$ ",
            },
            "images": [{"src": "https://wooloja.com.br/wp-content/uploads/escova.jpg"}],
            "average_rating": "4.8",
            "review_count": 142,
        }
    ]
    monkeypatch.setattr(PR, "http", lambda: FakeHTTP(lambda url, **kw: FakeResp(json_data=wc_payload)))
    items = PR.scout_woocommerce_store("https://wooloja.com.br", limit=5)
    assert len(items) == 1
    assert items[0]["platform"] == "woocommerce"
    assert items[0]["best_seller_rank"] == 1
    assert items[0]["discount_pct"] == 35
    assert items[0]["rating"] == 4.8
    assert items[0]["reviews_count"] == 142


def test_scout_nuvemshop_html_parsing(monkeypatch):
    catalog_html = """
    <html><body>
      <a href="/produtos/dispensador-automatico-sabao">Dispensador Automático</a>
    </body></html>
    """
    product_html = """
    <html>
    <head>
      <title>Dispensador Automático de Sabão com Sensor</title>
      <meta property="og:title" content="Dispensador Automático de Sabão com Sensor">
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Dispensador Automático de Sabão com Sensor",
        "image": ["https://d2r9epyceweg5n.cloudfront.net/stores/dispensador.jpg"],
        "offers": {
          "@type": "Offer",
          "price": "89.90",
          "highPrice": "149.90",
          "priceCurrency": "BRL"
        }
      }
      </script>
    </head>
    <body>
      <ul><li>Sensor infravermelho sem toque em 0.2s</li></ul>
    </body>
    </html>
    """

    def fake_get(url, **kw):
        if "/produtos/dispensador" in url:
            return FakeResp(text=product_html)
        return FakeResp(text=catalog_html)

    monkeypatch.setattr(PR, "http", lambda: FakeHTTP(fake_get))
    items = PR.scout_nuvemshop_store("https://lojanuvem.com.br", "Loja Nuvem", limit=4)
    assert len(items) == 1
    assert items[0]["title"] == "Dispensador Automático de Sabão com Sensor"
    assert items[0]["platform"] == "nuvemshop"
    assert items[0]["best_seller_rank"] == 1
    assert items[0]["discount_pct"] == 40
    assert items[0]["images"] == ["https://d2r9epyceweg5n.cloudfront.net/stores/dispensador.jpg"]


def test_history_products_affiliate_links_and_topic_builder(tmp_path, settings):
    h = History(tmp_path / "history.db")
    stores = h.ensure_default_stores(PR.DEFAULT_STORES)
    assert len(stores) >= 3

    pid1 = h.upsert_product({
        "url": "https://loja.com/products/mini-liquidificador",
        "title": "Mini Liquidificador Portátil 6 Lâminas",
        "short_name": "Mini Liquidificador",
        "platform": "shopify",
        "store_name": "Loja",
        "price": "R$ 69,90",
        "compare_price": "R$ 119,90",
        "discount_pct": 42,
        "best_seller_rank": 1,
        "viral_score": 88,
        "pain_point": "Sem tempo de preparar shake fora de casa",
        "hook_idea": "Ele tritura até gelo dentro da mochila!",
        "visual_angle": "Gelo sendo triturado na garrafa portátil",
        "benefits": ["6 lâminas inox", "Bateria USB-C"],
        "images": ["https://loja.com/img1.jpg"],
        "videos": ["https://loja.com/vid1.mp4"],
    })
    pid2 = h.upsert_product({
        "url": "https://loja.com/products/amassador-alho",
        "title": "Triturador Elétrico de Alho e Temperos Mini",
        "short_name": "Triturador de Alho",
        "platform": "nuvemshop",
        "store_name": "Loja",
        "price": "R$ 39,90",
        "best_seller_rank": 2,
        "viral_score": 84,
        "pain_point": "Mão ficando com cheiro forte de alho",
        "hook_idea": "Nunca mais fique com cheiro de alho nos dedos!",
        "visual_angle": "Apertando um botão e picando o alho em 2 segundos",
        "benefits": ["1 toque", "Lavável"],
        "images": ["https://loja.com/img2.jpg"],
        "affiliate_url": "https://s.shopee.com.br/alho-afiliado",
    })

    # Setting affiliate link on product 1 and ensuring re-upsert preserves it
    assert h.set_product_affiliate(pid1, "https://amzn.to/liquidificador-afiliado")
    h.upsert_product({
        "url": "https://loja.com/products/mini-liquidificador",
        "title": "Mini Liquidificador Portátil 6 Lâminas",
        "viral_score": 90,
    })
    prods = h.get_products([pid1, pid2])
    assert prods[0]["affiliate_url"] == "https://amzn.to/liquidificador-afiliado"
    assert prods[1]["affiliate_url"] == "https://s.shopee.com.br/alho-afiliado"

    # Multi-product topic ("Top Achadinhos")
    topic = PR.build_product_topic(prods)
    assert topic.product_ids == [pid1, pid2]
    assert topic.product_links == [
        "Mini Liquidificador: https://amzn.to/liquidificador-afiliado",
        "Triturador de Alho: https://s.shopee.com.br/alho-afiliado",
    ]
    assert "https://loja.com/img1.jpg" in topic.images
    assert "https://loja.com/vid1.mp4" in topic.videos
    assert "DOSSIÊ VERIFICADO DE PRODUTOS VIRAIS" in topic.context

    # Script Doctor prompt includes the verified dossier context
    script = Script(
        topic="2 Achadinhos",
        title="2 Achadinhos de Cozinha #shorts",
        hook_text="2 ACHADINHOS VIRAIS",
        scenes=[
            Scene("Esse mini liquidificador tritura gelo na mochila.", "portable blender ice", "blender", product="Mini Liquidificador"),
            Scene("E esse triturador pica alho em 2 segundos sem cheiro na mão! Qual você escolheria, 1 ou 2?", "garlic chopper", "chopper", product="Triturador de Alho"),
        ],
        description="Os 2 melhores gadgets de cozinha!",
        hashtags=["#achadinhos", "#shorts"],
        style="product",
        language="pt",
        product_links=topic.product_links,
    )
    _, user_prompt = review_prompt(script, settings, rewrite=True, context=topic.context)
    assert "Verified source facts & product dossier" in user_prompt
    assert "Mini Liquidificador" in user_prompt

    # final_description includes affiliate links formatted cleanly before hashtags
    desc = final_description(script)
    assert "Mini Liquidificador: https://amzn.to/liquidificador-afiliado" in desc
    assert "Triturador de Alho: https://s.shopee.com.br/alho-afiliado" in desc
    assert desc.index("Mini Liquidificador: https://amzn.to/liquidificador-afiliado") < desc.index("#shorts")


class _InMemorySocket:
    def __init__(self, req_bytes: bytes):
        self._rfile = io.BytesIO(req_bytes)
        self._wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        return self._rfile if "r" in mode else self._wfile

    def sendall(self, data: bytes):
        self._wfile.write(data)

    def close(self):
        pass


def call_handler(app, method: str, path: str, body=None, token: str | None = None):
    handler_cls = ST._handler(app, "127.0.0.1")
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = [
        f"{method} {path} HTTP/1.1",
        "Host: 127.0.0.1:8765",
        "Content-Type: application/json",
        f"Content-Length: {len(payload)}",
    ]
    if token:
        headers.append(f"X-Studio-Token: {token}")
    raw_req = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + payload
    sock = _InMemorySocket(raw_req)

    class DummyServer:
        server_name = "127.0.0.1"
        server_port = 8765

    handler_cls(sock, ("127.0.0.1", 55555), DummyServer())
    resp_bytes = sock._wfile.getvalue()
    head, _, resp_body = resp_bytes.partition(b"\r\n\r\n")
    status_line = head.splitlines()[0].decode("latin1")
    status = int(status_line.split()[1])
    return status, resp_body


def test_studio_products_endpoints_and_draft_with_affiliate_links(settings):
    app = ST.StudioServer(settings.with_overrides(upload=False))
    status, body = call_handler(app, "GET", "/api/products")
    assert status == 200
    data = json.loads(body)
    assert len(data["stores"]) >= 3

    # Add a store
    status, body = call_handler(
        app, "POST", "/api/products/stores",
        {"url": "https://minhaloja.myshopify.com", "name": "Minha Loja", "platform": "shopify", "niche": "tech"},
        app.token,
    )
    assert status == 200
    sid = json.loads(body)["id"]

    # Insert a product directly into history and test affiliate/star/draft endpoints
    pid = app.studio.history.upsert_product({
        "url": "https://minhaloja.myshopify.com/products/projetor-4k",
        "title": "Mini Projetor Portátil Smart Wi-Fi",
        "short_name": "Mini Projetor",
        "platform": "shopify",
        "store_name": "Minha Loja",
        "price": "R$ 299,90",
        "viral_score": 91,
        "pain_point": "TV cara para o quarto",
        "hook_idea": "Transformei a parede do quarto num cinema de 120 polegadas!",
        "visual_angle": "Projeção gigante na parede escura",
        "benefits": ["120 polegadas", "Android integrado"],
        "images": ["https://minhaloja.myshopify.com/proj.jpg"],
    })

    # Set affiliate link via API
    status, body = call_handler(
        app, "POST", f"/api/products/{pid}/affiliate",
        {"affiliate_url": "https://s.shopee.com.br/projetor-viral"},
        app.token,
    )
    assert status == 200
    assert json.loads(body)["affiliate_url"] == "https://s.shopee.com.br/projetor-viral"

    # Toggle star
    status, body = call_handler(app, "POST", f"/api/products/{pid}/star", {}, app.token)
    assert status == 200 and json.loads(body)["starred"] is True

    # Queue product into Ideas queue
    status, body = call_handler(app, "POST", "/api/ideas", {"product_ids": [pid], "style": "product"}, app.token)
    assert status == 200
    ideas = json.loads(call_handler(app, "GET", "/api/ideas")[1])["pending"]
    assert ideas[0]["notes"] == f"products:{pid}"

    # Offline draft job from product_ids preserves affiliate product_links
    status, body = call_handler(
        app, "POST", "/api/draft",
        {"offline": True, "style": "product", "product_ids": [pid]},
        app.token,
    )
    assert status == 200
    jid = json.loads(body)["job"]
    for _ in range(100):
        job = json.loads(call_handler(app, "GET", f"/api/jobs/{jid}")[1])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["product_ids"] == [pid]
    assert job["result"]["script"]["product_links"] == ["Mini Projetor: https://s.shopee.com.br/projetor-viral"]

    # Clean up store and product
    assert call_handler(app, "POST", f"/api/products/{pid}/delete", {}, app.token)[0] == 200
    assert call_handler(app, "POST", f"/api/products/stores/{sid}/delete", {}, app.token)[0] == 200


def test_product_scene_media_mapping_and_visuals_cycling(tmp_path, settings, monkeypatch):
    from types import SimpleNamespace
    from purffle_shorts import media as MD

    def fake_download(url, dest, **kw):
        dest.write_bytes(b"fake-media")
        return dest

    monkeypatch.setattr(MD, "download", fake_download)

    prods = [
        {
            "id": 1,
            "title": "Mop Spray Giratório",
            "short_name": "Mop Spray",
            "videos": ["https://cdn.example.com/mop.mp4"],
            "images": ["https://cdn.example.com/mop1.jpg"],
        },
        {
            "id": 2,
            "title": "Escova Elétrica 7 em 1",
            "short_name": "Escova Elétrica",
            "videos": [],
            "images": ["https://cdn.example.com/escova1.jpg", "https://cdn.example.com/escova2.jpg"],
        },
    ]
    scenes = [
        Scene("Cena 1 mop", "mop", "mop", product="1. Mop Spray"),
        Scene("Cena 2 mop", "mop", "mop", product="1. Mop Spray"),
        Scene("Cena 3 mop", "mop", "mop", product="1. Mop Spray"),
        Scene("Cena 4 escova", "brush", "brush", product="2. Escova Elétrica"),
        Scene("Cena 5 escova", "brush", "brush", product="2. Escova Elétrica"),
    ]
    timeline = [SimpleNamespace(index=i, duration=3.0) for i in range(len(scenes))]
    scene_media = PR.build_scene_media_for_products(prods, scenes, timeline, offline=False)
    assert len(scene_media) == 5
    # Scene 0 gets Mop video first, Scene 1 gets Mop image first, Scene 2 cycles back to Mop video!
    assert scene_media[0][0].url == "https://cdn.example.com/mop.mp4"
    assert scene_media[1][0].url == "https://cdn.example.com/mop1.jpg"
    assert scene_media[2][0].url == "https://cdn.example.com/mop.mp4"
    # Scene 3 and 4 get Escova images in order!
    assert scene_media[3][0].url == "https://cdn.example.com/escova1.jpg"
    assert scene_media[4][0].url == "https://cdn.example.com/escova2.jpg"

    s_online = settings.with_overrides(offline=False, visual_sources=["local"])
    vis = MD.Visuals(s_online, set(), repeat_extra=True, scene_media=scene_media)
    jobs = [(sc.search_query, sc.image_prompt, 3.0) for sc in scenes]
    items = vis.for_scenes(jobs, "2 Achadinhos", tmp_path / "media")
    assert [it.url for it in items] == [
        "https://cdn.example.com/mop.mp4",
        "https://cdn.example.com/mop1.jpg",
        "https://cdn.example.com/mop.mp4",
        "https://cdn.example.com/escova1.jpg",
        "https://cdn.example.com/escova2.jpg",
    ]


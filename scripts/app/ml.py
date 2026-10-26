"""Mercado Livre: login OAuth, escolha de categoria e publicação pela API oficial.
Credenciais e tokens ficam em db/secrets.json (fora do banco e nunca devolvidos para a GUI)."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from paths import DATA

SECRETS = DATA / "db" / "secrets.json"
API = "https://api.mercadolibre.com"
AUTH = "https://auth.mercadolivre.com.br/authorization"
REDIRECT = "http://localhost:8765/api/ml/callback"


def _load():
    return json.loads(SECRETS.read_text(encoding="utf-8")) if SECRETS.exists() else {}


def _save(d):
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_text(json.dumps(d, indent=1), encoding="utf-8")


def status():
    s = _load()
    return dict(configured=bool(s.get("client_id") and s.get("client_secret")), connected=bool(s.get("refresh_token")), user_id=s.get("user_id"))


def save_credentials(client_id, client_secret):
    if not re.fullmatch(r"\d{4,20}", client_id) or not re.fullmatch(r"[A-Za-z0-9]{10,64}", client_secret):
        raise ValueError("App ID (só números) ou Secret Key (letras e números) com formato inesperado")
    _save(_load() | dict(client_id=client_id, client_secret=client_secret))


def auth_url():
    s = _load()
    if not s.get("client_id"):
        raise ValueError("salve o App ID e a Secret Key primeiro")
    return AUTH + "?" + urllib.parse.urlencode(dict(response_type="code", client_id=s["client_id"], redirect_uri=REDIRECT))


def _token(form):
    s = _load()
    body = urllib.parse.urlencode(dict(client_id=s["client_id"], client_secret=s["client_secret"]) | form).encode()
    req = urllib.request.Request(API + "/oauth/token", body, {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        raise ValueError(f"o ML recusou o login: {_why(e)}")
    _save(s | dict(access_token=r["access_token"], refresh_token=r["refresh_token"], user_id=r.get("user_id"), expires_at=time.time() + r["expires_in"] - 60))


def exchange_code(code_or_url):
    """Aceita o código (TG-...) ou a URL inteira para a qual o ML redirecionou."""
    m = re.search(r"code=([^&\s]+)", code_or_url) or re.fullmatch(r"\s*(TG-[\w-]+)\s*", code_or_url)
    if not m:
        raise ValueError("não achei o código TG-... no texto colado")
    _token(dict(grant_type="authorization_code", code=m.group(1), redirect_uri=REDIRECT))


def _why(e):
    try:
        d = json.load(e)
        return "; ".join([d.get("message", "")] + [c.get("message", str(c)) if isinstance(c, dict) else str(c) for c in d.get("cause", [])])[:400]
    except Exception:
        return f"HTTP {e.code}"


def call(method, path, body=None, auth=True, multipart=None):
    """Chamada à API. body vira JSON; multipart = (nome_do_campo, nome_do_arquivo, bytes). Erros viram ValueError em português."""
    s = _load()
    headers = {"Accept": "application/json"}
    if auth:
        if not s.get("refresh_token"):
            raise ValueError("conecte sua conta do Mercado Livre antes")
        if s.get("expires_at", 0) < time.time():
            _token(dict(grant_type="refresh_token", refresh_token=s["refresh_token"]))
            s = _load()
        headers["Authorization"] = "Bearer " + s["access_token"]
    data = None
    if multipart:
        field, fname, blob = multipart
        edge = uuid.uuid4().hex
        data = (f'--{edge}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\nContent-Type: image/jpeg\r\n\r\n').encode() + blob + f"\r\n--{edge}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={edge}"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    try:
        r = urllib.request.urlopen(urllib.request.Request(API + path, data, headers, method=method), timeout=60)
        raw = r.read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise ValueError(f"o ML respondeu com erro: {_why(e)}")
    except urllib.error.URLError:
        raise ValueError("sem conexão com o Mercado Livre")


def categories(title):
    r = call("GET", "/sites/MLB/domain_discovery/search?" + urllib.parse.urlencode(dict(q=title, limit=6)), auth=False)
    return [dict(category_id=x["category_id"], name=x.get("category_name", ""), domain=x.get("domain_name", "")) for x in r]


def required_attributes(category_id):
    if not re.fullmatch(r"MLB\d+", category_id):
        raise ValueError("categoria inválida")
    out = []
    for a in call("GET", f"/categories/{category_id}/attributes", auth=False):
        t = a.get("tags", {})
        if t.get("required") or t.get("catalog_required"):
            out.append(dict(id=a["id"], name=a.get("name", a["id"]), values=[v["name"] for v in a.get("values", [])][:30]))
    return out


def build_item(cand, category_id, attributes, picture_ids, brand="", quantity=5, days="3"):
    """Corpo do POST /items. attributes: {id: valor}. Peça sob encomenda: prazo de fabricação entra como condição de venda."""
    attrs = [dict(id=k, value_name=str(v)) for k, v in attributes.items() if str(v).strip()]
    return dict(title=cand["kit"]["title"], category_id=category_id, price=round(cand["target_price"], 2), currency_id="BRL",
                available_quantity=int(quantity), buying_mode="buy_it_now", listing_type_id="gold_special", condition="new",
                pictures=[dict(id=i) for i in picture_ids], attributes=attrs,
                sale_terms=[dict(id="MANUFACTURING_TIME", value_name=f"{int(days)} dias")],
                shipping=dict(mode="me2", local_pick_up=False, free_shipping=False))


def validate(item):
    call("POST", "/items/validate", item)  # 204 sem corpo quando está tudo certo


def publish(item, description, image_files):
    ids = [call("POST", "/pictures/items/upload", multipart=("file", f.name, f.read_bytes()))["id"] for f in image_files]
    item = item | dict(pictures=[dict(id=i) for i in ids])
    r = call("POST", "/items", item)
    call("POST", f"/items/{r['id']}/description", dict(plain_text=description))
    return r["id"], r.get("permalink", "")

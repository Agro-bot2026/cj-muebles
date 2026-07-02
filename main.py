# CJ Muebles — Paso 2: DB + login
import os, sqlite3, hashlib, hmac, secrets, time
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from contextlib import contextmanager
from fastapi import FastAPI, Request, Form, UploadFile, File
import uuid
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "muebleria.db")

app = FastAPI(title="CJ Muebles")
app.add_middleware(SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "cambiar-en-paso-6"), max_age=43200,
    https_only=True, same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

# --- Headers de seguridad en todas las respuestas ---
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "media-src 'self' https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'"
        )
        return resp

app.add_middleware(SecurityHeaders)

tpl = Jinja2Templates(directory=os.path.join(BASE, "templates"))

@contextmanager
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con; con.commit()
    finally:
        con.close()

def hash_pass(p, salt):
    return hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), 100_000).hex()

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS ajustes(clave TEXT PRIMARY KEY, valor TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS categorias(
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
            orden INTEGER DEFAULT 0, visible INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS productos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria_id INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
            nombre TEXT NOT NULL, descripcion TEXT DEFAULT '',
            precio TEXT DEFAULT '', precio_oferta TEXT DEFAULT '',
            destacado INTEGER DEFAULT 0, visible INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            creado TEXT DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS media(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL, archivo TEXT NOT NULL, orden INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS conversaciones(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL, rol TEXT NOT NULL, mensaje TEXT NOT NULL,
            fecha TEXT DEFAULT (datetime('now','localtime')));
        """)
        if not con.execute("SELECT 1 FROM ajustes WHERE clave='admin_hash'").fetchone():
            salt = secrets.token_hex(16)
            con.execute("INSERT INTO ajustes VALUES('admin_salt',?)", (salt,))
            con.execute("INSERT INTO ajustes VALUES('admin_hash',?)", (hash_pass("cambiar123", salt),))
            con.execute("INSERT INTO ajustes VALUES('admin_user','admin')")
        for k, v in {"nombre_negocio":"CJ Muebles","eslogan":"Muebles para tu hogar",
            "promo":"","whatsapp":"","telefono":"","direccion":"","horarios":"",
            "instagram":"","facebook":"","email":"","telegram":"","tiktok":"","web":""}.items():
            con.execute("INSERT OR IGNORE INTO ajustes VALUES(?,?)", (k, v))

init_db()

def aj():
    with db() as con:
        return {r["clave"]: r["valor"] for r in con.execute("SELECT * FROM ajustes")}

BASE_URL = "https://cj-muebles.charly-tricks.dev"

def wsp_link(a, p):
    num = a.get("whatsapp", "")
    if not num:
        return ""
    import urllib.parse as u
    txt = u.quote(f"Hola! Me interesa: {p['nombre']} ({BASE_URL}/#p{p['id']})")
    return f"https://wa.me/{num}?text={txt}"

def cargar(rows, a):
    out = []
    for r in rows:
        d = dict(r)
        d["whatsapp_link"] = wsp_link(a, r)
        out.append(d)
    return out

@app.get("/", response_class=HTMLResponse)
@app.head("/")
def home(request: Request):
    a = aj()
    with db() as con:
        menu = con.execute("SELECT * FROM categorias WHERE visible=1 ORDER BY orden, nombre").fetchall()
        base = """SELECT p.*, c.nombre AS categoria,
              (SELECT archivo FROM media WHERE producto_id=p.id AND tipo='foto' ORDER BY orden LIMIT 1) AS foto,
              (SELECT archivo FROM media WHERE producto_id=p.id AND tipo='video' LIMIT 1) AS video
            FROM productos p LEFT JOIN categorias c ON c.id=p.categoria_id
            WHERE p.visible=1 """
        productos = con.execute(base + "ORDER BY p.orden, p.id DESC").fetchall()
        destacados = con.execute(base + "AND p.destacado=1 ORDER BY p.orden, p.id DESC LIMIT 8").fetchall()
    return tpl.TemplateResponse(request, "tienda.html", {
        "aj": a, "menu": menu,
        "productos": cargar(productos, a), "destacados": cargar(destacados, a)})

@app.get("/admin/login", response_class=HTMLResponse)
def login_form(request: Request):
    return tpl.TemplateResponse(request, "admin/login.html", {"error": None})


# --- Anti-fuerza bruta en el login ---
LOGIN_FALLOS = defaultdict(list)
LOGIN_MAX = 5          # intentos fallidos
LOGIN_BLOQUEO = 900    # bloqueo de 15 minutos

def login_bloqueado(ip):
    ahora = time.time()
    LOGIN_FALLOS[ip] = [t for t in LOGIN_FALLOS[ip] if ahora - t < LOGIN_BLOQUEO]
    return len(LOGIN_FALLOS[ip]) >= LOGIN_MAX

def login_fallo(ip):
    LOGIN_FALLOS[ip].append(time.time())

def login_reset(ip):
    LOGIN_FALLOS.pop(ip, None)

@app.post("/admin/login")
def login(request: Request, usuario: str = Form(...), clave: str = Form(...)):
    ip = ip_cliente(request)
    if login_bloqueado(ip):
        return tpl.TemplateResponse(request, "admin/login.html",
            {"error": "Demasiados intentos. Esperá 15 minutos e intentá de nuevo."})
    a = aj()
    if usuario == a.get("admin_user") and hmac.compare_digest(
            hash_pass(clave, a.get("admin_salt","")), a.get("admin_hash","")):
        login_reset(ip)
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    login_fallo(ip)
    return tpl.TemplateResponse(request, "admin/login.html", {"error": "Usuario o clave incorrectos"})

@app.get("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        n_prod = con.execute("SELECT COUNT(*) c FROM productos").fetchone()["c"]
        n_cat = con.execute("SELECT COUNT(*) c FROM categorias").fetchone()["c"]
        n_dest = con.execute("SELECT COUNT(*) c FROM productos WHERE destacado=1").fetchone()["c"]
    return tpl.TemplateResponse(request, "admin/dashboard.html",
        {"nav": "inicio", "n_prod": n_prod, "n_cat": n_cat, "n_dest": n_dest})


@app.get("/admin/categorias", response_class=HTMLResponse)
def adm_categorias(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        cats = con.execute("SELECT * FROM categorias ORDER BY orden, nombre").fetchall()
    return tpl.TemplateResponse(request, "admin/categorias.html", {"nav": "menu", "cats": cats})


@app.post("/admin/categorias/nueva")
def cat_nueva(request: Request, nombre: str = Form(...)):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        m = con.execute("SELECT COALESCE(MAX(orden),0)+1 o FROM categorias").fetchone()["o"]
        con.execute("INSERT INTO categorias(nombre,orden) VALUES(?,?)", (nombre.strip(), m))
    return RedirectResponse("/admin/categorias", status_code=303)


@app.post("/admin/categorias/{cid}/editar")
def cat_editar(request: Request, cid: int, nombre: str = Form(...),
               orden: int = Form(0), visible: int = Form(0)):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        con.execute("UPDATE categorias SET nombre=?, orden=?, visible=? WHERE id=?",
                    (nombre.strip(), orden, visible, cid))
    return RedirectResponse("/admin/categorias", status_code=303)


@app.post("/admin/categorias/{cid}/borrar")
def cat_borrar(request: Request, cid: int):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        con.execute("DELETE FROM categorias WHERE id=?", (cid,))
    return RedirectResponse("/admin/categorias", status_code=303)


UPLOADS = os.path.join(BASE, "static", "uploads")
EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
EXT_VIDEO = {".mp4", ".webm"}

async def guardar_archivo(f, exts, max_mb):
    if not f or not f.filename:
        return None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in exts:
        return None
    data = await f.read()
    if len(data) > max_mb * 1024 * 1024:
        return None
    nombre = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOADS, nombre), "wb") as out:
        out.write(data)
    return nombre

def borrar_archivo(nombre):
    ruta = os.path.join(UPLOADS, nombre)
    if os.path.isfile(ruta):
        os.remove(ruta)

def sesion(request):
    return request.session.get("admin")

@app.get("/admin/productos", response_class=HTMLResponse)
def adm_productos(request: Request):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        prods = con.execute("""
            SELECT p.*, c.nombre AS categoria,
              (SELECT archivo FROM media WHERE producto_id=p.id AND tipo='foto' ORDER BY orden LIMIT 1) AS foto,
              (SELECT archivo FROM media WHERE producto_id=p.id AND tipo='video' LIMIT 1) AS video
            FROM productos p LEFT JOIN categorias c ON c.id=p.categoria_id
            ORDER BY p.id DESC""").fetchall()
        cats = con.execute("SELECT * FROM categorias ORDER BY orden, nombre").fetchall()
    return tpl.TemplateResponse(request, "admin/productos.html",
        {"nav": "productos", "prods": prods, "cats": cats})

@app.get("/admin/productos/nuevo", response_class=HTMLResponse)
@app.get("/admin/productos/{pid}/editar", response_class=HTMLResponse)
def prod_form(request: Request, pid: int = None):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    p = fotos = video = None
    with db() as con:
        if pid:
            p = con.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
            if p:
                fotos = con.execute(
                    "SELECT * FROM media WHERE producto_id=? AND tipo='foto' ORDER BY orden", (pid,)).fetchall()
                video = con.execute(
                    "SELECT * FROM media WHERE producto_id=? AND tipo='video' LIMIT 1", (pid,)).fetchone()
        cats = con.execute("SELECT * FROM categorias ORDER BY orden, nombre").fetchall()
    return tpl.TemplateResponse(request, "admin/producto_form.html",
        {"nav": "productos", "p": p, "fotos": fotos, "video": video, "cats": cats})

@app.post("/admin/productos/guardar")
async def prod_guardar(request: Request, pid: int = Form(0), nombre: str = Form(...),
        categoria_id: int = Form(0), descripcion: str = Form(""),
        precio: str = Form(""), precio_oferta: str = Form(""), video_url: str = Form(""),
        destacado: int = Form(0), visible: int = Form(0), orden: int = Form(0),
        fotos: list[UploadFile] = File(default=[]), video: UploadFile = File(default=None)):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    cat = categoria_id or None
    with db() as con:
        if pid:
            con.execute("""UPDATE productos SET nombre=?, categoria_id=?, descripcion=?,
                precio=?, precio_oferta=?, video_url=?, destacado=?, visible=?, orden=? WHERE id=?""",
                (nombre.strip(), cat, descripcion, precio.strip(), precio_oferta.strip(), video_url.strip(),
                 destacado, visible, orden, pid))
        else:
            cur = con.execute("""INSERT INTO productos(nombre,categoria_id,descripcion,
                precio,precio_oferta,video_url,destacado,visible,orden) VALUES(?,?,?,?,?,?,?,?,?)""",
                (nombre.strip(), cat, descripcion, precio.strip(), precio_oferta.strip(), video_url.strip(),
                 destacado, visible, orden))
            pid = cur.lastrowid
        for f in fotos:
            arch = await guardar_archivo(f, EXT_FOTO, 8)
            if arch:
                m = con.execute("SELECT COALESCE(MAX(orden),0)+1 o FROM media WHERE producto_id=?",
                                (pid,)).fetchone()["o"]
                con.execute("INSERT INTO media(producto_id,tipo,archivo,orden) VALUES(?,'foto',?,?)",
                            (pid, arch, m))
        arch_v = await guardar_archivo(video, EXT_VIDEO, 40)
        if arch_v:
            viejo = con.execute("SELECT * FROM media WHERE producto_id=? AND tipo='video'",
                                (pid,)).fetchone()
            if viejo:
                borrar_archivo(viejo["archivo"])
                con.execute("DELETE FROM media WHERE id=?", (viejo["id"],))
            con.execute("INSERT INTO media(producto_id,tipo,archivo) VALUES(?,'video',?)", (pid, arch_v))
    return RedirectResponse(f"/admin/productos/{pid}/editar", status_code=303)

@app.post("/admin/productos/{pid}/borrar")
def prod_borrar(request: Request, pid: int):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        for m in con.execute("SELECT archivo FROM media WHERE producto_id=?", (pid,)):
            borrar_archivo(m["archivo"])
        con.execute("DELETE FROM productos WHERE id=?", (pid,))
    return RedirectResponse("/admin/productos", status_code=303)

@app.post("/admin/media/{mid}/borrar")
def media_borrar(request: Request, mid: int):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    with db() as con:
        m = con.execute("SELECT * FROM media WHERE id=?", (mid,)).fetchone()
        if m:
            borrar_archivo(m["archivo"])
            con.execute("DELETE FROM media WHERE id=?", (mid,))
            return RedirectResponse(f"/admin/productos/{m['producto_id']}/editar", status_code=303)
    return RedirectResponse("/admin/productos", status_code=303)


CLAVES_AJ = ["nombre_negocio","eslogan","promo","whatsapp","telefono",
             "direccion","horarios","instagram","facebook","email","telegram","tiktok","web"]

@app.get("/admin/ajustes", response_class=HTMLResponse)
def adm_ajustes(request: Request, ok: int = 0):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    return tpl.TemplateResponse(request, "admin/ajustes.html",
        {"nav": "ajustes", "aj": aj(), "ok": ok})

@app.post("/admin/ajustes")
async def guardar_ajustes(request: Request):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    form = await request.form()
    with db() as con:
        for k in CLAVES_AJ:
            con.execute("INSERT OR REPLACE INTO ajustes VALUES(?,?)", (k, form.get(k, "").strip()))
    return RedirectResponse("/admin/ajustes?ok=1", status_code=303)

@app.post("/admin/clave")
def cambiar_clave(request: Request, actual: str = Form(...), nueva: str = Form(...)):
    if not sesion(request):
        return RedirectResponse("/admin/login", status_code=303)
    a = aj()
    if not hmac.compare_digest(hash_pass(actual, a["admin_salt"]), a["admin_hash"]):
        return RedirectResponse("/admin/ajustes?ok=2", status_code=303)
    salt = secrets.token_hex(16)
    with db() as con:
        con.execute("INSERT OR REPLACE INTO ajustes VALUES('admin_salt',?)", (salt,))
        con.execute("INSERT OR REPLACE INTO ajustes VALUES('admin_hash',?)", (hash_pass(nueva, salt),))
    return RedirectResponse("/admin/ajustes?ok=3", status_code=303)


import httpx
from fastapi import Body
# --- Rate limit del chatbot (anti-abuso de la API) ---
import time
from collections import defaultdict
RATE_CHAT = defaultdict(list)
RATE_MAX = 12          # mensajes permitidos
RATE_VENTANA = 60      # por cada 60 segundos
RATE_MAX_DIA = 200     # tope diario por IP
RATE_DIA = defaultdict(list)

def ip_cliente(request):
    # Detrás de Cloudflare/Nginx la IP real viene en estos headers
    xff = request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "0"))

def rate_ok(ip):
    ahora = time.time()
    RATE_CHAT[ip] = [t for t in RATE_CHAT[ip] if ahora - t < RATE_VENTANA]
    RATE_DIA[ip] = [t for t in RATE_DIA[ip] if ahora - t < 86400]
    if len(RATE_CHAT[ip]) >= RATE_MAX or len(RATE_DIA[ip]) >= RATE_MAX_DIA:
        return False
    RATE_CHAT[ip].append(ahora); RATE_DIA[ip].append(ahora)
    return True



def contexto_negocio():
    a = aj()
    with db() as con:
        prods = con.execute("""SELECT p.nombre, p.descripcion, p.precio, p.precio_oferta,
              c.nombre AS categoria
            FROM productos p LEFT JOIN categorias c ON c.id=p.categoria_id
            WHERE p.visible=1 ORDER BY c.orden, p.orden""").fetchall()
    lineas = []
    for p in prods:
        precio = f"OFERTA {p['precio_oferta']} (antes {p['precio']})" if p['precio_oferta'] else (p['precio'] or "Consultar")
        cat = f"[{p['categoria']}] " if p['categoria'] else ""
        desc = f" — {p['descripcion']}" if p['descripcion'] else ""
        lineas.append(f"- {cat}{p['nombre']}: {precio}{desc}")
    catalogo = "\n".join(lineas) if lineas else "(catálogo vacío por ahora)"

    contacto = []
    if a.get("whatsapp"): contacto.append(f"WhatsApp: https://wa.me/{a['whatsapp']}")
    if a.get("telefono"): contacto.append(f"Teléfono: {a['telefono']}")
    if a.get("email"): contacto.append(f"Email: {a['email']}")
    if a.get("direccion"): contacto.append(f"Dirección: {a['direccion']}")
    if a.get("horarios"): contacto.append(f"Horarios: {a['horarios']}")
    if a.get("instagram"): contacto.append(f"Instagram: {a['instagram']}")
    if a.get("facebook"): contacto.append(f"Facebook: {a['facebook']}")
    if a.get("telegram"): contacto.append(f"Telegram: {a['telegram']}")
    if a.get("tiktok"): contacto.append(f"TikTok: {a['tiktok']}")
    if a.get("web"): contacto.append(f"Web: {a['web']}")
    contacto = "\n".join(contacto) if contacto else "(sin datos de contacto cargados)"

    return a.get("nombre_negocio","La mueblería"), catalogo, contacto

def system_prompt():
    nombre, catalogo, contacto = contexto_negocio()
    return f"""Sos el asistente de ventas de {nombre}, una mueblería. Atendés a clientes por el chat de la web.

CATÁLOGO ACTUAL (es la única fuente de verdad sobre productos y precios):
{catalogo}

DATOS DE CONTACTO:
{contacto}

REGLAS:
- Respondé SOLO con información de este catálogo y estos datos. Si te preguntan por algo que no está, decí que no lo tenés listado y ofrecé mostrar lo que sí hay o pasar el contacto.
- NUNCA inventes precios, productos, medidas ni datos que no figuren arriba.
- Sé cordial, breve y argentino (tuteo, tono de vendedor amable de Mendoza).
- Cuando el cliente muestre interés en comprar o pida precio/disponibilidad, invitalo a escribir por WhatsApp si está disponible.
- Si preguntan por contacto, ubicación, horarios o redes, dá exactamente los datos de arriba.
- Respuestas cortas, de 1 a 3 frases salvo que pidan detalle."""

@app.post("/api/chat")
async def api_chat(request: Request, payload: dict = Body(...)):
    if not rate_ok(ip_cliente(request)):
        return {"respuesta": "Estás enviando muchos mensajes muy rápido. Esperá un momento 🙏"}
    pregunta = (payload.get("mensaje") or "").strip()[:500]
    historial = payload.get("historial") or []
    if not pregunta:
        return {"respuesta": "Contame qué mueble estás buscando 🙂"}
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {"respuesta": "El asistente no está configurado todavía."}
    mensajes = [{"role": "system", "content": system_prompt()}]
    for h in historial[-6:]:
        r = h.get("rol"); c = (h.get("texto") or "")[:500]
        if r in ("user", "assistant") and c:
            mensajes.append({"role": r, "content": c})
    mensajes.append({"role": "user", "content": pregunta})
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "deepseek-chat", "messages": mensajes,
                      "temperature": 0.4, "max_tokens": 400})
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return {"respuesta": txt}
    except Exception as e:
        print("ERROR deepseek:", repr(e))
        return {"respuesta": "Uy, tuve un problema para responder. Probá de nuevo o escribinos por WhatsApp."}


from fastapi.responses import PlainTextResponse, Response

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return """User-agent: *
Allow: /
Disallow: /admin
Disallow: /api/
Sitemap: https://cj-muebles.charly-tricks.dev/sitemap.xml
"""

@app.get("/sitemap.xml")
def sitemap():
    urls = ['<url><loc>https://cj-muebles.charly-tricks.dev/</loc><priority>1.0</priority></url>']
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + '</urlset>'
    return Response(content=xml, media_type="application/xml")

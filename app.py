# app.py
"""
MVP backend para plataforma de trueques (un solo archivo).
Tecnologías: Flask, SQLAlchemy (SQLite), Flask-JWT-Extended.
Guardar este archivo como app.py y ejecutar: python app.py
"""

import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from flask_cors import CORS

# --- Configuración básica ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
# Ajustar CORS para permitir todas las rutas y supports_credentials=True
CORS(app, supports_credentials=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'swapmvp.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = "cambia_esto_por_un_secreto_en_produccion"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max por petición

db = SQLAlchemy(app)
jwt = JWTManager(app)

# --- Modelos ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    foto = db.Column(db.String(300), nullable=True)
    bio = db.Column(db.String(300), nullable=True)
    ciudad = db.Column(db.String(120), nullable=True)
    reputacion = db.Column(db.Integer, default=0)
    coins = db.Column(db.Integer, default=0)
    ranking_score = db.Column(db.Integer, default=0)  # total de trueques completados
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    objects = db.relationship("Objeto", backref="owner", lazy=True)
    incentives = db.relationship("IncentiveHistory", backref="user", lazy=True)


class Objeto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fotos = db.Column(db.String(1000), nullable=True)  # almacenaremos JSON-string (csv simple)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(1000), nullable=True)
    categoria = db.Column(db.String(50), nullable=False)  # Ropa, Electrodomesticos, Decoracion
    estado = db.Column(db.String(50), nullable=False)  # Nuevo, Semi-nuevo, Usado
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_ultimo_movimiento = db.Column(db.DateTime, default=datetime.utcnow)
    visible = db.Column(db.Boolean, default=True)
    likes = db.Column(db.Integer, default=0)  # simple contador para popularidad

    def fotos_list(self):
        if not self.fotos:
            return []
        return self.fotos.split(",")


class Trueque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    objeto_ofrecido_id = db.Column(db.Integer, db.ForeignKey('objeto.id'), nullable=True)
    objeto_solicitado_id = db.Column(db.Integer, db.ForeignKey('objeto.id'), nullable=False)
    usuario_origen_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    usuario_destino_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    estado = db.Column(db.String(50), default="pendiente")  # pendiente, aceptado, rechazado, finalizado
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_cierre = db.Column(db.DateTime, nullable=True)

    # relaciones simples
    messages = db.relationship("ChatMessage", backref="trueque", lazy=True)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trueque_id = db.Column(db.Integer, db.ForeignKey('trueque.id'), nullable=False)
    usuario_envia_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mensaje = db.Column(db.String(2000), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class IncentiveHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tipo_incentivo = db.Column(db.String(50), nullable=False)  # coins, badge, ranking
    valor = db.Column(db.String(200), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mensaje = db.Column(db.String(500), nullable=False)
    leida = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


# ONGs / Eventos (página estática)
class ONG(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(1000), nullable=True)
    enlace = db.Column(db.String(500), nullable=True)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(1000), nullable=True)
    fecha = db.Column(db.DateTime, nullable=False)
    lugar = db.Column(db.String(200), nullable=True)


# --- Helpers ---
def serialize_user(u: User):
    return {
        "id": u.id,
        "nombre": u.nombre,
        "email": u.email,
        "foto": u.foto,
        "bio": u.bio,
        "ciudad": u.ciudad,
        "reputacion": u.reputacion,
        "coins": u.coins,
        "ranking_score": u.ranking_score,
        "fecha_registro": u.fecha_registro.isoformat()
    }

def login_required_json(fn):
    """Decorador para endpoints que requieren token; devuelve JSON consistente"""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper

# --- Rutas de utilidades (archivos) ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Autenticación ---
@app.route("/register", methods=["POST"])
def register():
    data = request.form or request.get_json()
    if not data:
        return jsonify({"msg":"No data provided"}), 400
    nombre = data.get("nombre")
    email = data.get("email")
    password = data.get("password")
    ciudad = data.get("ciudad")
    bio = data.get("bio")
    if not (nombre and email and password):
        return jsonify({"msg":"nombre, email y password son obligatorios"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"msg":"Email ya registrado"}), 400
    pwd_hash = generate_password_hash(password)
    user = User(nombre=nombre, email=email, password_hash=pwd_hash, ciudad=ciudad, bio=bio)
    db.session.add(user)
    db.session.commit()
    # Nota: no asignamos coins hasta que publique un objeto.
    return jsonify({"msg":"Usuario creado", "user": serialize_user(user)}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.json or request.form
    email = data.get("email")
    password = data.get("password")
    if not (email and password):
        return jsonify({"msg":"email y password requeridos"}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"msg":"Credenciales inválidas"}), 401
    token = create_access_token(identity=str(user.id))
    return jsonify({"access_token": token, "user": serialize_user(user)})

@app.route("/me", methods=["GET"])
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    user = User.query.get(uid)
    return jsonify(serialize_user(user))

# --- Perfil (editar) ---
@app.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    uid = int(get_jwt_identity())
    user = User.query.get(uid)
    data = request.form or request.json
    if 'foto' in request.files:
        f = request.files['foto']
        filename = secure_filename(f.filename)
        unique = f"{uuid.uuid4().hex}_{filename}"
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], unique))
        user.foto = url_for('uploaded_file', filename=unique, _external=False)
    if data:
        user.nombre = data.get("nombre", user.nombre)
        user.bio = data.get("bio", user.bio)
        user.ciudad = data.get("ciudad", user.ciudad)
    db.session.commit()
    return jsonify({"msg":"Perfil actualizado", "user": serialize_user(user)})

# --- Publicar objeto (express) ---
ALLOWED_EXT = {'png','jpg','jpeg','gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXT

@app.route("/objects", methods=["POST"])
@jwt_required()
def create_object():
    """
    Publicar objeto rápido:
    Campos: fotos (1-3), titulo, descripcion, categoria, estado
    Regla: publicación en <30s -> es responsabilidad del frontend, aquí asumimos request rápido.
    Incentivos: +20 coins por publicar
               +50 coins si publica dentro de 24h desde fecha_registro
               si publica 5+ objetos en un día -> marca para descuento (se registra en incentives)
    """
    uid = int(get_jwt_identity())
    user = User.query.get(uid)
    # parsing multipart/form-data o json
    title = request.form.get("titulo") or (request.json and request.json.get("titulo"))
    if not title:
        return jsonify({"msg":"titulo es requerido"}), 400
    descripcion = request.form.get("descripcion") or (request.json and request.json.get("descripcion"))
    categoria = request.form.get("categoria") or (request.json and request.json.get("categoria"))
    estado = request.form.get("estado") or (request.json and request.json.get("estado"))
    if categoria not in ("Ropa","Electrodomésticos","Decoración"):
        return jsonify({"msg":"categoria inválida. Usa Ropa, Electrodomésticos o Decoración"}), 400
    if estado not in ("Nuevo","Semi-nuevo","Usado"):
        return jsonify({"msg":"estado inválido. Usa Nuevo, Semi-nuevo o Usado"}), 400

    # manejar fotos
    fotos_files = []
    if 'fotos' in request.files:
        fobjs = request.files.getlist("fotos")
        for f in fobjs[:3]:
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                unique = f"{uuid.uuid4().hex}_{filename}"
                path = os.path.join(app.config['UPLOAD_FOLDER'], unique)
                f.save(path)
                fotos_files.append(url_for('uploaded_file', filename=unique, _external=False))
    else:
        # si frontend envía photos como URLs en JSON
        fotos_json = (request.json and request.json.get("fotos")) or []
        if isinstance(fotos_json, list):
            fotos_files = fotos_json[:3]

    if len(fotos_files) < 1:
        return jsonify({"msg":"Se requiere al menos 1 foto"}), 400

    objeto = Objeto(
        usuario_id = uid,
        fotos = ",".join(fotos_files),
        titulo = title,
        descripcion = descripcion,
        categoria = categoria,
        estado = estado,
        fecha_creacion = datetime.utcnow(),
        fecha_ultimo_movimiento = datetime.utcnow(),
        visible = True
    )
    db.session.add(objeto)
    db.session.commit()

    # Incentivos: +20 coins por publicar
    user.coins += 20
    db.session.add(IncentiveHistory(usuario_id=uid, tipo_incentivo="coins", valor="+20"))
    # +50 si publica dentro de primeras 24h del registro
    if datetime.utcnow() - user.fecha_registro <= timedelta(hours=24):
        user.coins += 50
        db.session.add(IncentiveHistory(usuario_id=uid, tipo_incentivo="coins", valor="+50 (bonus 24h)"))
    # regla: si publica 5+ objetos en un día -> se guarda un record (incentive) para aplicar descuento al gastar
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count_today = Objeto.query.filter(Objeto.usuario_id==uid, Objeto.fecha_creacion >= today_start).count()
    if count_today >= 5:
        # marcado en incentives (frontend/back puede usar para aplicar 20% descuento)
        db.session.add(IncentiveHistory(usuario_id=uid, tipo_incentivo="discount", valor="20% publishing streak"))

    db.session.commit()
    return jsonify({"msg":"Objeto publicado", "objeto_id": objeto.id})

# --- Listado y búsqueda de objetos (marketplace) ---
@app.route("/objects", methods=["GET"])
def list_objects():
    """
    Filtros: categoria, estado, ciudad (proximidad simple), order (nuevos, intercambiados, populares)
    Pagination simple: page, per_page
    """
    categoria = request.args.get("categoria")
    estado = request.args.get("estado")
    ciudad = request.args.get("ciudad")  # proximidad: igual ciudad
    order = request.args.get("order", "nuevos")  # nuevos, intercambiados, populares
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    q = Objeto.query.filter_by(visible=True)

    if categoria:
        q = q.filter_by(categoria=categoria)
    if estado:
        q = q.filter_by(estado=estado)
    if ciudad:
        # prox: filtrar owners en misma ciudad
        q = q.join(User, Objeto.usuario_id==User.id).filter(User.ciudad==ciudad)

    if order == "nuevos":
        q = q.order_by(Objeto.fecha_creacion.desc())
    elif order == "intercambiados":
        # usaremos 'fecha_ultimo_movimiento' como proxy
        q = q.order_by(Objeto.fecha_ultimo_movimiento.desc())
    elif order == "populares":
        q = q.order_by(Objeto.likes.desc())

    total = q.count()
    items = q.offset((page-1)*per_page).limit(per_page).all()

    def ser(o):
        return {
            "id": o.id,
            "usuario_id": o.usuario_id,
            "fotos": o.fotos_list(),
            "titulo": o.titulo,
            "descripcion": o.descripcion,
            "categoria": o.categoria,
            "estado": o.estado,
            "fecha_creacion": o.fecha_creacion.isoformat(),
            "fecha_ultimo_movimiento": o.fecha_ultimo_movimiento.isoformat(),
            "likes": o.likes
        }
    return jsonify({"total": total, "page": page, "per_page": per_page, "items": [ser(i) for i in items]})

@app.route("/objects/<int:obj_id>", methods=["GET"])
def get_object(obj_id):
    o = Objeto.query.get_or_404(obj_id)
    owner = User.query.get(o.usuario_id)
    return jsonify({
        "id": o.id,
        "usuario": serialize_user(owner),
        "fotos": o.fotos_list(),
        "titulo": o.titulo,
        "descripcion": o.descripcion,
        "categoria": o.categoria,
        "estado": o.estado,
        "fecha_creacion": o.fecha_creacion.isoformat(),
        "fecha_ultimo_movimiento": o.fecha_ultimo_movimiento.isoformat(),
        "visible": o.visible
    })

# --- Proponer trueque ---
@app.route("/trade/propose", methods=["POST"])
@jwt_required()
def propose_trade():
    uid = int(get_jwt_identity())
    data = request.json or request.form
    objeto_solicitado_id = data.get("objeto_solicitado_id")
    objeto_ofrecido_id = data.get("objeto_ofrecido_id")  # opcional
    if not objeto_solicitado_id:
        return jsonify({"msg":"objeto_solicitado_id requerido"}), 400
    obj_s = Objeto.query.get(objeto_solicitado_id)
    if not obj_s:
        return jsonify({"msg":"objeto solicitado no existe"}), 404
    if obj_s.usuario_id == uid:
        return jsonify({"msg":"No puedes solicitar tu propio objeto"}), 400
    dest_user = User.query.get(obj_s.usuario_id)
    tr = Trueque(
        objeto_ofrecido_id = objeto_ofrecido_id,
        objeto_solicitado_id = objeto_solicitado_id,
        usuario_origen_id = uid,
        usuario_destino_id = obj_s.usuario_id,
        estado = "pendiente"
    )
    db.session.add(tr)
    db.session.commit()
    # notificación simple al dueño
    db.session.add(Notification(usuario_id=obj_s.usuario_id, mensaje=f"Tienes una nueva propuesta de trueque para '{obj_s.titulo}'"))
    db.session.commit()
    return jsonify({"msg":"Propuesta creada", "trueque_id": tr.id})

@app.route("/trade/<int:trade_id>", methods=["GET"])
@jwt_required()
def get_trade(trade_id):
    tr = Trueque.query.get_or_404(trade_id)
    return jsonify({
        "id": tr.id,
        "objeto_ofrecido_id": tr.objeto_ofrecido_id,
        "objeto_solicitado_id": tr.objeto_solicitado_id,
        "usuario_origen_id": tr.usuario_origen_id,
        "usuario_destino_id": tr.usuario_destino_id,
        "estado": tr.estado,
        "fecha_creacion": tr.fecha_creacion.isoformat(),
        "fecha_cierre": tr.fecha_cierre.isoformat() if tr.fecha_cierre else None
    })

@app.route("/trade/<int:trade_id>/accept", methods=["POST"])
@jwt_required()
def accept_trade(trade_id):
    uid = int(get_jwt_identity())
    tr = Trueque.query.get_or_404(trade_id)
    if tr.usuario_destino_id != uid:
        return jsonify({"msg":"Solo el usuario destino puede aceptar"}), 403
    tr.estado = "aceptado"
    tr.fecha_cierre = None
    db.session.commit()
    # Crear chat inicial (vacío, chat messages se usan para coordinar)
    db.session.add(Notification(usuario_id=tr.usuario_origen_id, mensaje=f"Tu propuesta {tr.id} fue aceptada. Puedes chatear para coordinar."))
    # actualizar fecha_ultimo_movimiento del objeto solicitado
    obj_req = Objeto.query.get(tr.objeto_solicitado_id)
    if obj_req:
        obj_req.fecha_ultimo_movimiento = datetime.utcnow()
    db.session.commit()
    return jsonify({"msg":"Trueque aceptado"})

@app.route("/trade/<int:trade_id>/reject", methods=["POST"])
@jwt_required()
def reject_trade(trade_id):
    uid = int(get_jwt_identity())
    tr = Trueque.query.get_or_404(trade_id)
    if tr.usuario_destino_id != uid:
        return jsonify({"msg":"Solo el usuario destino puede rechazar"}), 403
    tr.estado = "rechazado"
    tr.fecha_cierre = datetime.utcnow()
    db.session.commit()
    db.session.add(Notification(usuario_id=tr.usuario_origen_id, mensaje=f"Tu propuesta {tr.id} fue rechazada."))
    db.session.commit()
    return jsonify({"msg":"Trueque rechazado"})

@app.route("/trade/<int:trade_id>/counter", methods=["POST"])
@jwt_required()
def counter_proposal(trade_id):
    """
    Proponer alternativa: el destino puede proponer otro objeto propio (ofrecido) o dejar vacío
    """
    uid = int(get_jwt_identity())
    tr = Trueque.query.get_or_404(trade_id)
    if tr.usuario_destino_id != uid:
        return jsonify({"msg":"Solo destino puede proponer alternativa"}), 403
    data = request.json or request.form
    new_ofrecido = data.get("objeto_ofrecido_id")  # id de objeto del destino (opcional)
    tr.objeto_ofrecido_id = new_ofrecido
    tr.estado = "pendiente"  # sigue pendiente hasta respuesta origen
    db.session.commit()
    db.session.add(Notification(usuario_id=tr.usuario_origen_id, mensaje=f"Tu propuesta {tr.id} recibió una alternativa."))
    db.session.commit()
    return jsonify({"msg":"Alternativa propuesta"})

@app.route("/trade/<int:trade_id>/finalize", methods=["POST"])
@jwt_required()
def finalize_trade(trade_id):
    """
    Se marca como finalizado (ambos acuerdan fuera de app). Se actualiza ranking y badges simples.
    """
    uid = int(get_jwt_identity())
    tr = Trueque.query.get_or_404(trade_id)
    # cualquiera de los dos usuarios puede marcar finalizado (en la app idealmente ambos confirman)
    if uid not in (tr.usuario_origen_id, tr.usuario_destino_id):
        return jsonify({"msg":"No autorizado"}), 403
    tr.estado = "finalizado"
    tr.fecha_cierre = datetime.utcnow()
    # actualizar ranking_score de ambos
    u1 = User.query.get(tr.usuario_origen_id)
    u2 = User.query.get(tr.usuario_destino_id)
    if u1:
        u1.ranking_score = (u1.ranking_score or 0) + 1
    if u2:
        u2.ranking_score = (u2.ranking_score or 0) + 1
    db.session.add(IncentiveHistory(usuario_id=u1.id, tipo_incentivo="ranking", valor="+1") if u1 else None)
    db.session.add(IncentiveHistory(usuario_id=u2.id, tipo_incentivo="ranking", valor="+1") if u2 else None)
    # badges: Eco-Warrior: si tiene 3+ intercambios completados
    for u in (u1,u2):
        if u and u.ranking_score >= 3:
            db.session.add(IncentiveHistory(usuario_id=u.id, tipo_incentivo="badge", valor="Eco-Warrior"))
    # actualizar objetos fecha_ultimo_movimiento
    for oid in (tr.objeto_ofrecido_id, tr.objeto_solicitado_id):
        if oid:
            obj = Objeto.query.get(oid)
            if obj:
                obj.fecha_ultimo_movimiento = datetime.utcnow()
    db.session.commit()
    return jsonify({"msg":"Trueque marcado como finalizado"})

# --- Chat simple ---
@app.route("/trade/<int:trade_id>/messages", methods=["GET","POST"])
@jwt_required()
def trade_messages(trade_id):
    uid = int(get_jwt_identity())
    tr = Trueque.query.get_or_404(trade_id)
    if uid not in (tr.usuario_origen_id, tr.usuario_destino_id):
        return jsonify({"msg":"No autorizado"}), 403
    if request.method == "POST":
        data = request.json or request.form
        txt = data.get("mensaje")
        if not txt:
            return jsonify({"msg":"mensaje requerido"}), 400
        m = ChatMessage(trueque_id=trade_id, usuario_envia_id=uid, mensaje=txt)
        db.session.add(m)
        db.session.commit()
        # enviar notificación simple al otro
        other = tr.usuario_origen_id if uid==tr.usuario_destino_id else tr.usuario_destino_id
        db.session.add(Notification(usuario_id=other, mensaje=f"Nuevo mensaje en trueque {trade_id}"))
        db.session.commit()
        return jsonify({"msg":"Mensaje enviado"})
    else:
        msgs = ChatMessage.query.filter_by(trueque_id=trade_id).order_by(ChatMessage.timestamp.asc()).all()
        out = []
        for m in msgs:
            out.append({
                "id": m.id,
                "usuario_envia_id": m.usuario_envia_id,
                "mensaje": m.mensaje,
                "timestamp": m.timestamp.isoformat()
            })
        return jsonify(out)

# --- Incentives, badges y ranking ---
@app.route("/user/<int:user_id>/incentives", methods=["GET"])
def get_incentives(user_id):
    items = IncentiveHistory.query.filter_by(usuario_id=user_id).order_by(IncentiveHistory.fecha.desc()).all()
    return jsonify([{"tipo":i.tipo_incentivo,"valor":i.valor,"fecha":i.fecha.isoformat()} for i in items])

@app.route("/ranking", methods=["GET"])
def ranking():
    users = User.query.order_by(User.ranking_score.desc()).limit(50).all()
    return jsonify([{"id":u.id,"nombre":u.nombre,"ranking_score":u.ranking_score,"reputacion":u.reputacion} for u in users])

@app.route("/badges/<int:user_id>", methods=["GET"])
def user_badges(user_id):
    badges = IncentiveHistory.query.filter_by(usuario_id=user_id, tipo_incentivo="badge").all()
    return jsonify([b.valor for b in badges])

# --- Notificaciones ---
@app.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    uid = int(get_jwt_identity())
    notes = Notification.query.filter_by(usuario_id=uid).order_by(Notification.fecha.desc()).all()
    return jsonify([{"id":n.id,"mensaje":n.mensaje,"leida":n.leida,"fecha":n.fecha.isoformat()} for n in notes])

@app.route("/notifications/<int:notif_id>/read", methods=["POST"])
@jwt_required()
def mark_read(notif_id):
    uid = int(get_jwt_identity())
    n = Notification.query.get_or_404(notif_id)
    if n.usuario_id != uid:
        return jsonify({"msg":"No autorizado"}), 403
    n.leida = True
    db.session.commit()
    return jsonify({"msg":"Marcada como leída"})

# Job para generar notificaciones sobre objetos inactivos.
def generate_inactive_notifications():
    """Busca objetos con fecha_ultimo_movimiento y crea notificaciones segun reglas:
       - 90 dias -> "¿Aún lo usas?"
       - 180 dias -> "6 meses sin interés..."
       - 90/180 definiciones en spec: usaremos 90 y 180 días.
    """
    now = datetime.utcnow()
    objs = Objeto.query.filter_by(visible=True).all()
    for o in objs:
        dias = (now - o.fecha_ultimo_movimiento).days
        user_id = o.usuario_id
        if dias >= 90 and dias < 91:  # exactamente alrededor de 90 días
            msg = f"Tu objeto '{o.titulo}' lleva 90 días sin moverse, ¿aún lo usas? (Sí/No)"
            db.session.add(Notification(usuario_id=user_id, mensaje=msg))
        if dias >= 180 and dias < 181:
            msg = f"Tu objeto '{o.titulo}' lleva 6 meses sin interés, considera destacarlo o bajarlo de precio."
            db.session.add(Notification(usuario_id=user_id, mensaje=msg))
    db.session.commit()

@app.route("/run_notifications", methods=["POST"])
def run_notifications_route():
    """Endpoint para ejecutar manualmente la generación de notificaciones (útil para pruebas o cron)."""
    generate_inactive_notifications()
    return jsonify({"msg":"Notificaciones generadas (manual run)."})

# --- Matching simple por reglas ---
@app.route("/matching/suggestions", methods=["GET"])
@jwt_required()
def suggestions():
    """
    Devuelve:
     - 'objetos_que_podrian_interesarte': basado en categoria que más publica el usuario y likes y ciudad
     - 'tu_objeto_podria_ayudar': reglas manuales para ONG segun categoria
    """
    uid = int(get_jwt_identity())
    user = User.query.get(uid)
    # categoria que más publica:
    from sqlalchemy import func
    cat_counts = db.session.query(Objeto.categoria, func.count(Objeto.id)).filter_by(usuario_id=uid).group_by(Objeto.categoria).all()
    top_cat = cat_counts[0][0] if cat_counts else None

    # objetos proximos en misma ciudad y categoria top_cat
    q = Objeto.query.join(User, Objeto.usuario_id==User.id).filter(User.ciudad==user.ciudad, Objeto.visible==True)
    if top_cat:
        q = q.filter(Objeto.categoria==top_cat)
    items = q.order_by(Objeto.fecha_creacion.desc()).limit(20).all()

    sugeridos = [{"id":o.id,"titulo":o.titulo,"categoria":o.categoria,"fotos":o.fotos_list()} for o in items]

    # reglas manuales para ONG
    def suggest_ong_for_obj(o: Objeto):
        if o.categoria == "Decoración":
            return "ONG de casas de acogida"
        if o.categoria == "Ropa":
            return "ONG de ayuda escolar"
        return None

    # devolver top N objetos user's own that podrían ayudar a causa
    my_objs = Objeto.query.filter_by(usuario_id=uid).all()
    ayuda = []
    for o in my_objs:
        r = suggest_ong_for_obj(o)
        if r:
            ayuda.append({"objeto_id": o.id, "titulo": o.titulo, "sugerencia": r})
    return jsonify({"objetos_que_podrian_interesarte": sugeridos, "tu_objeto_podria_ayudar": ayuda})

# --- ONG y Eventos ---
@app.route("/ngos", methods=["GET","POST"])
def ngos_list_create():
    if request.method == "POST":
        data = request.json or request.form
        nombre = data.get("nombre")
        if not nombre:
            return jsonify({"msg":"nombre requerido"}), 400
        ong = ONG(nombre=nombre, descripcion=data.get("descripcion"), enlace=data.get("enlace"))
        db.session.add(ong)
        db.session.commit()
        return jsonify({"msg":"ONG creada","id":ong.id})
    else:
        items = ONG.query.all()
        return jsonify([{"id":o.id,"nombre":o.nombre,"descripcion":o.descripcion,"enlace":o.enlace} for o in items])

@app.route("/events", methods=["GET","POST"])
def events_list_create():
    if request.method == "POST":
        data = request.json or request.form
        titulo = data.get("titulo")
        fecha_raw = data.get("fecha")
        if not (titulo and fecha_raw):
            return jsonify({"msg":"titulo y fecha son requeridos"}), 400
        fecha = datetime.fromisoformat(fecha_raw)
        ev = Event(titulo=titulo, descripcion=data.get("descripcion"), fecha=fecha, lugar=data.get("lugar"))
        db.session.add(ev)
        db.session.commit()
        return jsonify({"msg":"Evento creado","id":ev.id})
    else:
        items = Event.query.order_by(Event.fecha.asc()).all()
        return jsonify([{"id":e.id,"titulo":e.titulo,"fecha":e.fecha.isoformat(),"lugar":e.lugar} for e in items])

@app.route("/events/<int:event_id>/participate", methods=["POST"])
@jwt_required()
def participate_event(event_id):
    uid = int(get_jwt_identity())
    # Para MVP guardamos una notificación indicando interés
    ev = Event.query.get_or_404(event_id)
    db.session.add(Notification(usuario_id=uid, mensaje=f"Has mostrado interés en participar en '{ev.titulo}'"))
    db.session.commit()
    return jsonify({"msg":"Interés registrado"})

# --- Aux: CRUD objetos (editar / borrar) ---
@app.route("/objects/<int:obj_id>", methods=["PUT","DELETE"])
@jwt_required()
def edit_delete_object(obj_id):
    uid = int(get_jwt_identity())
    o = Objeto.query.get_or_404(obj_id)
    if o.usuario_id != uid:
        return jsonify({"msg":"No autorizado"}), 403
    if request.method == "DELETE":
        o.visible = False
        db.session.commit()
        return jsonify({"msg":"Objeto ocultado (borrado lógico)"})
    else:
        data = request.form or request.json
        o.titulo = data.get("titulo", o.titulo)
        o.descripcion = data.get("descripcion", o.descripcion)
        o.categoria = data.get("categoria", o.categoria)
        o.estado = data.get("estado", o.estado)
        # si suben nuevas fotos manejarlas (reemplazar)
        if 'fotos' in request.files:
            fotos_files = []
            fobjs = request.files.getlist("fotos")
            for f in fobjs[:3]:
                if f and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    unique = f"{uuid.uuid4().hex}_{filename}"
                    path = os.path.join(app.config['UPLOAD_FOLDER'], unique)
                    f.save(path)
                    fotos_files.append(url_for('uploaded_file', filename=unique, _external=False))
            if fotos_files:
                o.fotos = ",".join(fotos_files)
        db.session.commit()
        return jsonify({"msg":"Objeto actualizado"})

# --- Endpoint para gastar coins (aplicar 20% si aplica) ---
@app.route("/coins/spend", methods=["POST"])
@jwt_required()
def spend_coins():
    """
    Example: gastar coins para destacar un objeto (precio simulado).
    Si el usuario publicó >=5 objetos hoy, aplica 20% descuento.
    Request: { "amount": 100 }
    """
    uid = int(get_jwt_identity())
    data = request.json or request.form
    amount = int(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"msg":"amount invalido"}), 400
    user = User.query.get(uid)
    # check discount condition:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count_today = Objeto.query.filter(Objeto.usuario_id==uid, Objeto.fecha_creacion>=today_start).count()
    discount = 0.2 if count_today >=5 else 0.0
    final_amount = int(amount * (1 - discount))
    if user.coins < final_amount:
        return jsonify({"msg":"No tienes suficientes coins", "needed": final_amount, "have": user.coins}), 400
    user.coins -= final_amount
    db.session.add(IncentiveHistory(usuario_id=uid, tipo_incentivo="coins", valor=f"-{final_amount}"))
    db.session.commit()
    return jsonify({"msg":"Coins gastados", "final_amount": final_amount, "discount_applied": discount>0})

# --- Inicialización DB (ruta útil para primera ejecución) ---
@app.route("/init_db", methods=["POST"])
def init_db():
    db.create_all()
    return jsonify({"msg":"DB inicializada"})

# --- Run app ---

# Crear tablas al cargar la aplicación (compatible con Flask 3.x)
with app.app_context():
    try:
        db.create_all()
        print("Tablas creadas o ya existentes.")
    except Exception as e:
        print("Error creando tablas al iniciar la app:", e)

if __name__ == "__main__":
    # Si la DB no existe, crearla
    if not os.path.exists(os.path.join(BASE_DIR, 'swapmvp.db')):
        db.create_all()
        print("B creada (swapmvp.db)")
    app.run(host="0.0.0.0", port=5000, debug=True)

# --- Trueques recibidos ---

# Endpoint para obtener las solicitudes de trueque que el usuario ha recibido
@app.route("/trade/received", methods=["GET"])
@jwt_required()
def received_trades():
    """
    Devuelve los trueques recibidos por el usuario autenticado, con:
      - info de objeto solicitado (el del usuario destino)
      - info de objeto ofrecido (puede ser None)
      - info del usuario origen (el que propone)
    """
    uid = int(get_jwt_identity())
    trades = Trueque.query.filter_by(usuario_destino_id=uid).order_by(Trueque.fecha_creacion.desc()).all()
    def serialize_objeto(obj):
        if not obj:
            return None
        return {
            "id": obj.id,
            "usuario_id": obj.usuario_id,
            "fotos": obj.fotos_list(),
            "titulo": obj.titulo,
            "descripcion": obj.descripcion,
            "categoria": obj.categoria,
            "estado": obj.estado,
            "fecha_creacion": obj.fecha_creacion.isoformat(),
            "fecha_ultimo_movimiento": obj.fecha_ultimo_movimiento.isoformat(),
            "likes": obj.likes
        }
    result = []
    for t in trades:
        obj_solicitado = Objeto.query.get(t.objeto_solicitado_id) if t.objeto_solicitado_id else None
        obj_ofrecido = Objeto.query.get(t.objeto_ofrecido_id) if t.objeto_ofrecido_id else None
        user_origen = User.query.get(t.usuario_origen_id)
        result.append({
            "id": t.id,
            "estado": t.estado,
            "fecha_creacion": t.fecha_creacion.isoformat(),
            "fecha_cierre": t.fecha_cierre.isoformat() if t.fecha_cierre else None,
            "objeto_solicitado": serialize_objeto(obj_solicitado),
            "objeto_ofrecido": serialize_objeto(obj_ofrecido),
            "usuario_origen": serialize_user(user_origen)
        })
    return jsonify(result)

# --- Trueques enviados ---
@app.route("/trade/sent", methods=["GET"])
@jwt_required()
def sent_trades():
    uid = int(get_jwt_identity())
    trades = Trueque.query.filter_by(usuario_origen_id=uid).order_by(Trueque.fecha_creacion.desc()).all()

    def serialize_objeto(obj):
        if not obj:
            return None
        return {
            "id": obj.id,
            "usuario_id": obj.usuario_id,
            "fotos": obj.fotos_list(),
            "titulo": obj.titulo,
            "descripcion": obj.descripcion,
            "categoria": obj.categoria,
            "estado": obj.estado,
            "fecha_creacion": obj.fecha_creacion.isoformat(),
            "fecha_ultimo_movimiento": obj.fecha_ultimo_movimiento.isoformat(),
            "likes": obj.likes
        }

    result = []
    for t in trades:
        obj_solicitado = Objeto.query.get(t.objeto_solicitado_id) if t.objeto_solicitado_id else None
        obj_ofrecido = Objeto.query.get(t.objeto_ofrecido_id) if t.objeto_ofrecido_id else None
        user_dest = User.query.get(t.usuario_destino_id)
        result.append({
            "id": t.id,
            "estado": t.estado,
            "fecha_creacion": t.fecha_creacion.isoformat(),
            "fecha_cierre": t.fecha_cierre.isoformat() if t.fecha_cierre else None,
            "objeto_solicitado": serialize_objeto(obj_solicitado),
            "objeto_ofrecido": serialize_objeto(obj_ofrecido),
            "usuario_destino": serialize_user(user_dest)
        })
    return jsonify(result)
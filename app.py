import os
import hmac
import hashlib
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv

# --- IMPORTACIÓN DE CLOUDINARY ---
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Carga variables locales si existe un archivo .env (Local)
load_dotenv()

app = Flask(__name__)

# Llave secreta protegida
app.secret_key = os.getenv('SECRET_KEY', 'clave_secreta_muy_dificil_123').strip()

# --- UTILIDADES DE CONTRASEÑAS ---

def get_password_secret():
    secret = app.secret_key or os.getenv('SECRET_KEY')
    return secret if secret else 'fallback_secret_12345'


def hash_password(password: str) -> str:
    secret = get_password_secret().encode('utf-8')
    digest = hmac.new(secret, password.encode('utf-8'), hashlib.sha1).hexdigest()
    return f'sha1${digest}'


def verify_password(stored_password: str, password: str) -> bool:
    if not stored_password:
        return False
    if stored_password.startswith('sha1$'):
        return hmac.compare_digest(stored_password, hash_password(password))
    return stored_password == password


# --- CONFIGURACIÓN DE CLOUDINARY BLINDADA ---
# Extraemos directo del entorno limpiando espacios sucios. 
# Si no existen en el entorno, usa los de tu .env local automáticamente.
CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET')

if CLOUD_NAME and API_KEY and API_SECRET:
    cloudinary.config(
        cloud_name = CLOUD_NAME.strip(),
        api_key    = API_KEY.strip(),
        api_secret = API_SECRET.strip(),
        secure = True
    )
else:
    # Fallback de desarrollo por si tu .env local no cargó correctamente
    cloudinary.config(
        cloud_name = "dt0rtdlhi",
        api_key    = "432936586413485",
        api_secret = "6YXdQ-HXOkOmZbk_DQHjGsZU80k",
        secure = True
    )


# --- CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Modo Producción (Render)
        conn = psycopg2.connect(db_url.strip())
    else:
        # Modo Desarrollo (Localhost conectando a Railway)
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'yamanote.proxy.rlwy.net').strip(),
            database=os.getenv('DB_NAME', 'railway').strip(),
            user=os.getenv('DB_USER', 'postgres').strip(),
            password=os.getenv('DB_PASS', '110512').strip(),
            port=os.getenv('DB_PORT', '27092').strip()
        )
    return conn


def add_bar_percent(rows, value_index):
    max_value = max([row[value_index] or 0 for row in rows], default=0)
    enriched_rows = []

    for row in rows:
        value = row[value_index] or 0
        percent = round((value / max_value) * 100) if max_value else 0
        enriched_rows.append(row + (percent,))

    return enriched_rows

# --- RUTAS DE NAVEGACIÓN ---

@app.route('/')
def index():
    return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form['correo']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT "contraseña", rol, nombre FROM usuarios WHERE correo = %s', (correo,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result:
            stored_password, role, name = result[0], result[1], result[2]
            password_ok = verify_password(stored_password, password)

            if password_ok:
                if stored_password and not stored_password.startswith('sha1$'):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute('UPDATE usuarios SET "contraseña" = %s WHERE correo = %s', (hash_password(password), correo))
                    conn.commit()
                    cur.close()
                    conn.close()

                session['user'] = name
                session['rol'] = role
                if role and (role.upper() == 'ADMINISTRADOR' or role.upper() == 'ADMIN'):
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('user_dashboard'))
            else:
                flash('Credenciales inválidas', 'danger')
        else:
            flash('El usuario no existe', 'danger')
            
        return redirect(url_for('index'))
        
    return render_template('login.html')


@app.route('/administrador')
def admin_dashboard():
    if 'rol' in session and (session['rol'].upper() == 'ADMINISTRADOR' or session['rol'].upper() == 'ADMIN'):
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute('SELECT id_usuario, nombre, apellido, correo, telefono, rol, fecha_registro FROM usuarios ORDER BY id_usuario ASC')
        usuarios = cur.fetchall()
        
        cur.execute('SELECT COUNT(*) FROM productos')
        resultado_productos = cur.fetchone()
        total_prod = resultado_productos[0] if resultado_productos else 0
        
        cur.execute('SELECT COUNT(*) FROM clientes')
        resultado_clientes = cur.fetchone()
        total_clie = resultado_clientes[0] if resultado_clientes else 0
        
        cur.execute('SELECT COUNT(*) FROM ventas')
        resultado_ventas = cur.fetchone()
        total_vent = resultado_ventas[0] if resultado_ventas else 0
        
        cur.execute('SELECT COALESCE(SUM(cantidad), 0) FROM ventas')
        resultado_articulos = cur.fetchone()
        total_articulos_vendidos = resultado_articulos[0] if resultado_articulos else 0

        cur.execute('SELECT COALESCE(SUM(total), 0) FROM ventas WHERE fecha_salida::date = CURRENT_DATE')
        resultado_ingresos = cur.fetchone()
        total_ingre = resultado_ingresos[0] if resultado_ingresos and resultado_ingresos[0] is not None else 0
        
        cur.execute('SELECT COUNT(*) FROM productos WHERE stock = 0')
        resultado_sin_stock = cur.fetchone()
        total_sin_stk = resultado_sin_stock[0] if resultado_sin_stock else 0

        cur.execute('''
            SELECT id_producto, nombre, descripcion, precio, stock, marca, talla, color, imagen_url
            FROM productos
            WHERE stock = 0
            ORDER BY nombre ASC
        ''')
        productos_sin_stock = cur.fetchall()

        cur.execute('''
            SELECT p.id_producto, p.nombre, COALESCE(SUM(v.cantidad), 0) AS vendidos, COALESCE(SUM(v.total), 0) AS ingresos
            FROM productos p
            JOIN ventas v ON v.id_producto = p.id_producto
            GROUP BY p.id_producto, p.nombre
            ORDER BY vendidos DESC, ingresos DESC
            LIMIT 5
        ''')
        productos_mas_vendidos = add_bar_percent(cur.fetchall(), 2)

        cur.execute('''
            SELECT p.id_producto, p.nombre, COALESCE(SUM(v.cantidad), 0) AS vendidos, COALESCE(SUM(v.total), 0) AS ingresos
            FROM productos p
            LEFT JOIN ventas v ON v.id_producto = p.id_producto
            GROUP BY p.id_producto, p.nombre
            ORDER BY vendidos ASC, p.nombre ASC
            LIMIT 5
        ''')
        productos_menos_vendidos = add_bar_percent(cur.fetchall(), 2)

        cur.execute('''
            SELECT id_producto, nombre, stock, marca, talla, color
            FROM productos
            WHERE stock > 0 AND stock <= 5
            ORDER BY stock ASC, nombre ASC
            LIMIT 8
        ''')
        productos_stock_bajo = []
        for producto in cur.fetchall():
            stock = producto[2] or 0
            productos_stock_bajo.append(producto + (round((stock / 5) * 100),))
        
        cur.close()
        conn.close()
        
        return render_template('admin.html', 
                               usuarios=usuarios, 
                               total_productos=total_prod, 
                               total_clientes=total_clie, 
                               total_ventas=total_vent,
                               total_ingresos=total_ingre,
                               total_articulos_vendidos=total_articulos_vendidos,
                               total_sin_stock=total_sin_stk,
                               productos_sin_stock=productos_sin_stock,
                               productos_mas_vendidos=productos_mas_vendidos,
                               productos_menos_vendidos=productos_menos_vendidos,
                               productos_stock_bajo=productos_stock_bajo)
    else:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))


@app.route('/usuario')
def user_dashboard():
    if 'user' in session:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id_producto, nombre, descripcion, precio, stock, marca, talla, color, imagen_url 
            FROM productos 
            ORDER BY id_producto ASC
        ''')
        productos = cur.fetchall()
        cur.close()
        conn.close()
        es_admin = 'rol' in session and (session['rol'].upper() == 'ADMINISTRADOR' or session['rol'].upper() == 'ADMIN')
        productos_sin_stock = [producto for producto in productos if producto[4] == 0]
        return render_template(
            'usuario.html',
            productos=productos,
            es_admin=es_admin,
            productos_sin_stock=productos_sin_stock,
            total_sin_stock=len(productos_sin_stock)
        )
    return redirect(url_for('index'))


# --- CRUD USUARIOS ---

@app.route('/guardar_usuario', methods=['POST'])
def guardar_usuario():
    id_usuario = request.form.get('id_usuario')
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    correo = request.form['correo']
    password = request.form['password']
    telefono = request.form['telefono']
    rol = request.form['rol']

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if id_usuario and id_usuario.strip() != "":
            if password.strip() == "":
                cur.execute('''
                    UPDATE usuarios 
                    SET nombre=%s, apellido=%s, correo=%s, telefono=%s, rol=%s 
                    WHERE id_usuario=%s
                ''', (nombre, apellido, correo, telefono, rol, id_usuario))
            else:
                hashed = hash_password(password)
                cur.execute('''
                    UPDATE usuarios 
                    SET nombre=%s, apellido=%s, correo=%s, "contraseña"=%s, telefono=%s, rol=%s 
                    WHERE id_usuario=%s
                ''', (nombre, apellido, correo, hashed, telefono, rol, id_usuario))
            flash('Usuario actualizado correctamente', 'success')
        else:
            hashed = hash_password(password)
            cur.execute('''
                INSERT INTO usuarios (nombre, apellido, correo, "contraseña", telefono, rol, fecha_registro) 
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE)
            ''', (nombre, apellido, correo, hashed, telefono, rol))
            flash('Usuario registrado con éxito', 'success')
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'Error en la base de datos: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/eliminar_usuario/<int:id>')
def eliminar_usuario(id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM usuarios WHERE id_usuario = %s', (id,))
        conn.commit()
        flash('Usuario eliminado satisfactoriamente', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'No se pudo eliminar: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_dashboard'))


# --- CRUD DE CLIENTES ---

@app.route('/admin_clientes')
def admin_clientes():
    if 'rol' in session and (session['rol'].upper() == 'ADMINISTRADOR' or session['rol'].upper() == 'ADMIN'):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT id_clientes, nombre, apellido, correo, "contraseña", telefono FROM clientes ORDER BY id_clientes ASC')
        clientes = cur.fetchall()

        cur.execute('''
            SELECT
                v.id_ventas,
                v.id_clientes,
                COALESCE(p.nombre, 'Producto eliminado') AS producto,
                v.id_producto,
                v.cantidad,
                v.total,
                v.fecha_salida,
                v.talla,
                v.referencia_pago
            FROM ventas v
            LEFT JOIN productos p ON p.id_producto = v.id_producto
            ORDER BY v.fecha_salida DESC, v.id_ventas DESC
        ''')
        compras_clientes = cur.fetchall()

        cur.close()
        conn.close()
        return render_template('admin_clientes.html', clientes=clientes, compras_clientes=compras_clientes)
    else:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))


@app.route('/guardar_cliente', methods=['POST'])
def guardar_cliente():
    id_clientes = request.form.get('id_clientes')
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    correo = request.form['correo']
    password = request.form['password']
    telefono = request.form['telefono']

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if id_clientes and id_clientes.strip() != "":
            if password.strip() == "":
                cur.execute('''
                    UPDATE clientes 
                    SET nombre=%s, apellido=%s, correo=%s, telefono=%s 
                    WHERE id_clientes=%s
                ''', (nombre, apellido, correo, telefono, id_clientes))
            else:
                hashed_password = hashlib.sha256(password.encode()).hexdigest()
                cur.execute('''
                    UPDATE clientes 
                    SET nombre=%s, apellido=%s, correo=%s, "contraseña"=%s, telefono=%s 
                    WHERE id_clientes=%s
                ''', (nombre, apellido, correo, hashed_password, telefono, id_clientes))
            flash('Cliente actualizado correctamente', 'success')
        else:
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            cur.execute('''
                INSERT INTO clientes (nombre, apellido, correo, "contraseña", telefono) 
                VALUES (%s, %s, %s, %s, %s)
            ''', (nombre, apellido, correo, hashed_password, telefono))
            flash('Cliente registrado con éxito', 'success')
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'Error en la base de datos: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_clientes'))


@app.route('/eliminar_cliente/<int:id>')
def eliminar_cliente(id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM clientes WHERE id_clientes = %s', (id,))
        conn.commit()
        flash('Cliente eliminado satisfactoriamente', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'No se pudo eliminar al cliente: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_clientes'))


# --- VISTA DE AUDITORÍA DE VENTAS ---

@app.route('/admin_ventas')
def admin_ventas():
    if 'rol' in session and (session['rol'].upper() == 'ADMINISTRADOR' or session['rol'].upper() == 'ADMIN'):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id_ventas, id_producto, id_clientes, cantidad, total, fecha_salida, talla, referencia_pago 
            FROM ventas 
            ORDER BY id_ventas ASC
        ''')
        historial_ventas = cur.fetchall()
        
        cur.close()
        conn.close()
        return render_template('admin_ventas.html', ventas=historial_ventas)
    else:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))


# --- CRUD PRODUCTOS (CON SUBIDA OPTIMIZADA A CLOUDINARY) ---

@app.route('/guardar_producto', methods=['POST'])
def guardar_producto():
    id_producto = request.form.get('id_producto')
    nombre = request.form['nombre']
    descripcion = request.form['descripcion']
    precio = request.form['precio']
    stock = request.form['stock']
    marca = request.form.get('marca')
    talla = request.form.get('talla')
    color = request.form.get('color')
    
    file = request.files.get('imagen')
    cloudinary_url = None
    
    if file and file.filename != '':
        try:
            # Subida directa delegando la firma automática al SDK oficial
            upload_result = cloudinary.uploader.upload(
                file, 
                folder="productos_catalogo"
            )
            cloudinary_url = upload_result.get('secure_url')
        except Exception as upload_error:
            flash(f'Error al subir tu imagen a la nube: {upload_error}', 'danger')
            return redirect(url_for('user_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if id_producto and id_producto.strip() != "":
            if cloudinary_url:
                cur.execute('''
                    UPDATE productos 
                    SET nombre=%s, descripcion=%s, precio=%s, stock=%s, marca=%s, talla=%s, color=%s, imagen_url=%s 
                    WHERE id_producto=%s
                ''', (nombre, descripcion, precio, stock, marca, talla, color, cloudinary_url, id_producto))
            else:
                cur.execute('''
                    UPDATE productos 
                    SET nombre=%s, descripcion=%s, precio=%s, stock=%s, marca=%s, talla=%s, color=%s 
                    WHERE id_producto=%s
                ''', (nombre, descripcion, precio, stock, marca, talla, color, id_producto))
            flash('Producto actualizado con éxito', 'success')
        else:
            if not cloudinary_url:
                cloudinary_url = 'https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg'
                
            cur.execute('''
                INSERT INTO productos (nombre, descripcion, precio, stock, marca, talla, color, imagen_url) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (nombre, descripcion, precio, stock, marca, talla, color, cloudinary_url))
            flash('Producto agregado correctamente', 'success')
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'Error al guardar en la base de datos: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('user_dashboard'))


@app.route('/eliminar_producto/<int:id>')
def eliminar_producto(id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM productos WHERE id_producto = %s', (id,))
        conn.commit()
        flash('Producto eliminado con éxito', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'No se pudo eliminar el producto: {e}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('user_dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
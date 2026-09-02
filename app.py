from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, Response
)
import sqlite3
import csv
import io
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATABASE = "attendance.db"


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS college (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        college_name TEXT DEFAULT '',
        department TEXT DEFAULT '',
        class_name TEXT DEFAULT '',
        division TEXT DEFAULT '',
        academic_year TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL,
        prn TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        class_name TEXT DEFAULT '',
        division TEXT DEFAULT '',
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS lectures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        lecture_date TEXT NOT NULL,
        lecture_number INTEGER NOT NULL,
        locked INTEGER DEFAULT 0,
        UNIQUE(subject_id, lecture_date, lecture_number),
        FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lecture_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('P', 'A')),
        UNIQUE(lecture_id, student_id),
        FOREIGN KEY(lecture_id) REFERENCES lectures(id) ON DELETE CASCADE,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    """)

    # Default teacher
    user = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not user:
        conn.execute(
            """
            INSERT INTO users(username, password, full_name)
            VALUES (?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash("admin123"),
                "Administrator"
            )
        )

    # Default college setup
    conn.execute("""
        INSERT OR IGNORE INTO college
        (id, college_name, department, class_name, division, academic_year)
        VALUES (1, '', '', '', '', '')
    """)

    conn.commit()
    conn.close()


# --------------------------------------------------
# LOGIN REQUIRED
# --------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db()

    total_students = conn.execute(
        "SELECT COUNT(*) AS count FROM students WHERE active = 1"
    ).fetchone()["count"]

    total_subjects = conn.execute(
        "SELECT COUNT(*) AS count FROM subjects"
    ).fetchone()["count"]

    total_lectures = conn.execute(
        "SELECT COUNT(*) AS count FROM lectures"
    ).fetchone()["count"]

    total_present = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM attendance
        WHERE status = 'P'
        """
    ).fetchone()["count"]

    total_attendance = conn.execute(
        "SELECT COUNT(*) AS count FROM attendance"
    ).fetchone()["count"]

    percentage = 0

    if total_attendance > 0:
        percentage = round(
            total_present * 100 / total_attendance,
            2
        )

    college = conn.execute(
        "SELECT * FROM college WHERE id = 1"
    ).fetchone()

    conn.close()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        total_subjects=total_subjects,
        total_lectures=total_lectures,
        percentage=percentage,
        college=college
    )


# --------------------------------------------------
# COLLEGE SETTINGS
# --------------------------------------------------

@app.route("/settings", methods=["POST"])
@login_required
def settings():

    college_name = request.form.get("college_name", "")
    department = request.form.get("department", "")
    class_name = request.form.get("class_name", "")
    division = request.form.get("division", "")
    academic_year = request.form.get("academic_year", "")

    conn = get_db()

    conn.execute("""
        UPDATE college
        SET college_name = ?,
            department = ?,
            class_name = ?,
            division = ?,
            academic_year = ?
        WHERE id = 1
    """, (
        college_name,
        department,
        class_name,
        division,
        academic_year
    ))

    conn.commit()
    conn.close()

    flash("College settings updated.", "success")

    return redirect(url_for("dashboard"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not full_name or not username:
            flash("Name and username are required.", "danger")
            return redirect(url_for("account"))

        conn = get_db()

        try:
            if password:
                conn.execute("""
                    UPDATE users
                    SET username = ?, full_name = ?, password = ?
                    WHERE id = ?
                """, (
                    username,
                    full_name,
                    generate_password_hash(password),
                    session["user_id"]
                ))
            else:
                conn.execute("""
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE id = ?
                """, (username, full_name, session["user_id"]))

            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            flash("That username is already in use.", "danger")
            return redirect(url_for("account"))

        conn.close()
        session["username"] = username
        session["full_name"] = full_name
        flash("Account details updated.", "success")
        return redirect(url_for("account"))

    conn = get_db()
    user = conn.execute(
        "SELECT username, full_name FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()
    return render_template("account.html", user=user)


# --------------------------------------------------
# STUDENTS
# --------------------------------------------------

@app.route("/students")
@login_required
def students():

    search = request.args.get("search", "").strip()

    conn = get_db()

    if search:

        students = conn.execute("""
            SELECT *
            FROM students
            WHERE active = 1
            AND (
                name LIKE ?
                OR roll_no LIKE ?
                OR prn LIKE ?
            )
            ORDER BY CAST(roll_no AS INTEGER), name
        """, (
            f"%{search}%",
            f"%{search}%",
            f"%{search}%"
        )).fetchall()

    else:

        students = conn.execute("""
            SELECT *
            FROM students
            WHERE active = 1
            ORDER BY CAST(roll_no AS INTEGER), name
        """).fetchall()

    conn.close()

    return render_template(
        "students.html",
        students=students,
        search=search
    )


@app.route("/students/add", methods=["POST"])
@login_required
def add_student():

    roll_no = request.form.get("roll_no", "").strip()
    prn = request.form.get("prn", "").strip()
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    division = request.form.get("division", "").strip()

    if not roll_no or not prn or not name:
        flash("Roll number, PRN and name are required.", "danger")
        return redirect(url_for("students"))

    conn = get_db()

    try:

        conn.execute("""
            INSERT INTO students
            (roll_no, prn, name, class_name, division)
            VALUES (?, ?, ?, ?, ?)
        """, (
            roll_no,
            prn,
            name,
            class_name,
            division
        ))

        conn.commit()

        flash("Student added successfully.", "success")

    except sqlite3.IntegrityError:

        flash("PRN already exists.", "danger")

    finally:
        conn.close()

    return redirect(url_for("students"))


@app.route("/students/edit/<int:student_id>", methods=["POST"])
@login_required
def edit_student(student_id):

    roll_no = request.form.get("roll_no", "").strip()
    prn = request.form.get("prn", "").strip()
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    division = request.form.get("division", "").strip()

    conn = get_db()

    try:

        conn.execute("""
            UPDATE students
            SET roll_no = ?,
                prn = ?,
                name = ?,
                class_name = ?,
                division = ?
            WHERE id = ?
        """, (
            roll_no,
            prn,
            name,
            class_name,
            division,
            student_id
        ))

        conn.commit()

        flash("Student updated successfully.", "success")

    except sqlite3.IntegrityError:

        flash("PRN already belongs to another student.", "danger")

    finally:
        conn.close()

    return redirect(url_for("students"))


@app.route("/students/delete/<int:student_id>", methods=["POST"])
@login_required
def delete_student(student_id):

    conn = get_db()

    conn.execute(
        "UPDATE students SET active = 0 WHERE id = ?",
        (student_id,)
    )

    conn.commit()
    conn.close()

    flash("Student deleted.", "success")

    return redirect(url_for("students"))


# --------------------------------------------------
# SUBJECTS
# --------------------------------------------------

@app.route("/subjects")
@login_required
def subjects():

    conn = get_db()

    subjects = conn.execute("""
        SELECT *
        FROM subjects
        ORDER BY name
    """).fetchall()

    conn.close()

    return render_template(
        "subject.html",
        subjects=subjects
    )


@app.route("/subjects/add", methods=["POST"])
@login_required
def add_subject():

    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()

    if not name or not code:
        flash("Subject name and code are required.", "danger")
        return redirect(url_for("subjects"))

    conn = get_db()

    try:

        conn.execute("""
            INSERT INTO subjects(name, code)
            VALUES (?, ?)
        """, (name, code))

        conn.commit()

        flash("Subject added successfully.", "success")

    except sqlite3.IntegrityError:

        flash("Subject code already exists.", "danger")

    finally:
        conn.close()

    return redirect(url_for("subjects"))


@app.route("/subjects/delete/<int:subject_id>", methods=["POST"])
@login_required
def delete_subject(subject_id):

    conn = get_db()

    conn.execute(
        "DELETE FROM subjects WHERE id = ?",
        (subject_id,)
    )

    conn.commit()
    conn.close()

    flash("Subject deleted.", "success")

    return redirect(url_for("subjects"))


# --------------------------------------------------
# ATTENDANCE PAGE
# --------------------------------------------------

@app.route("/attendance")
@login_required
def attendance():

    conn = get_db()

    subjects = conn.execute(
        "SELECT * FROM subjects ORDER BY name"
    ).fetchall()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        ORDER BY CAST(roll_no AS INTEGER), name
    """).fetchall()

    conn.close()

    return render_template(
        "attendence.html",
        subjects=subjects,
        students=students,
        today=date.today().isoformat()
    )


# --------------------------------------------------
# CREATE / LOAD LECTURE
# --------------------------------------------------

@app.route("/api/lecture", methods=["POST"])
@login_required
def create_lecture():

    data = request.get_json()

    subject_id = data.get("subject_id")
    lecture_date = data.get("lecture_date")
    lecture_number = data.get("lecture_number")

    if not subject_id or not lecture_date or not lecture_number:
        return jsonify({
            "success": False,
            "message": "All lecture details are required."
        }), 400

    conn = get_db()

    lecture = conn.execute("""
        SELECT *
        FROM lectures
        WHERE subject_id = ?
        AND lecture_date = ?
        AND lecture_number = ?
    """, (
        subject_id,
        lecture_date,
        lecture_number
    )).fetchone()

    if lecture:

        lecture_id = lecture["id"]

    else:

        try:

            cursor = conn.execute("""
                INSERT INTO lectures
                (subject_id, lecture_date, lecture_number)
                VALUES (?, ?, ?)
            """, (
                subject_id,
                lecture_date,
                lecture_number
            ))

            lecture_id = cursor.lastrowid

            # Create default Absent records
            students = conn.execute("""
                SELECT id
                FROM students
                WHERE active = 1
            """).fetchall()

            for student in students:

                conn.execute("""
                    INSERT OR IGNORE INTO attendance
                    (lecture_id, student_id, status)
                    VALUES (?, ?, 'A')
                """, (
                    lecture_id,
                    student["id"]
                ))

            conn.commit()

        except sqlite3.IntegrityError:

            conn.rollback()

            lecture = conn.execute("""
                SELECT *
                FROM lectures
                WHERE subject_id = ?
                AND lecture_date = ?
                AND lecture_number = ?
            """, (
                subject_id,
                lecture_date,
                lecture_number
            )).fetchone()

            lecture_id = lecture["id"]

    attendance_rows = conn.execute("""
        SELECT student_id, status
        FROM attendance
        WHERE lecture_id = ?
    """, (lecture_id,)).fetchall()

    result = {
        str(row["student_id"]): row["status"]
        for row in attendance_rows
    }

    lecture = conn.execute(
        "SELECT * FROM lectures WHERE id = ?",
        (lecture_id,)
    ).fetchone()

    conn.close()

    return jsonify({
        "success": True,
        "lecture_id": lecture_id,
        "locked": bool(lecture["locked"]),
        "attendance": result
    })


# --------------------------------------------------
# SAVE ATTENDANCE
# --------------------------------------------------

@app.route("/api/attendance/save", methods=["POST"])
@login_required
def save_attendance():

    data = request.get_json()

    lecture_id = data.get("lecture_id")
    records = data.get("records", {})

    if not lecture_id:
        return jsonify({
            "success": False,
            "message": "Lecture not selected."
        }), 400

    conn = get_db()

    lecture = conn.execute("""
        SELECT *
        FROM lectures
        WHERE id = ?
    """, (lecture_id,)).fetchone()

    if not lecture:

        conn.close()

        return jsonify({
            "success": False,
            "message": "Lecture not found."
        }), 404

    if lecture["locked"]:

        conn.close()

        return jsonify({
            "success": False,
            "message": "Attendance is locked."
        }), 403

    for student_id, status in records.items():

        if status not in ["P", "A"]:
            continue

        conn.execute("""
            INSERT INTO attendance
            (lecture_id, student_id, status)
            VALUES (?, ?, ?)

            ON CONFLICT(lecture_id, student_id)
            DO UPDATE SET status = excluded.status
        """, (
            lecture_id,
            student_id,
            status
        ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Attendance saved successfully."
    })


# --------------------------------------------------
# LOCK / UNLOCK
# --------------------------------------------------

@app.route("/api/lecture/<int:lecture_id>/lock", methods=["POST"])
@login_required
def toggle_lock(lecture_id):

    conn = get_db()

    lecture = conn.execute(
        "SELECT locked FROM lectures WHERE id = ?",
        (lecture_id,)
    ).fetchone()

    if not lecture:

        conn.close()

        return jsonify({
            "success": False,
            "message": "Lecture not found."
        }), 404

    new_status = 0 if lecture["locked"] else 1

    conn.execute("""
        UPDATE lectures
        SET locked = ?
        WHERE id = ?
    """, (
        new_status,
        lecture_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "locked": bool(new_status)
    })


# --------------------------------------------------
# REPORTS
# --------------------------------------------------

@app.route("/reports")
@login_required
def reports():

    conn = get_db()

    subjects = conn.execute("""
        SELECT *
        FROM subjects
        ORDER BY name
    """).fetchall()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        ORDER BY CAST(roll_no AS INTEGER), name
    """).fetchall()

    report = []

    for student in students:

        total = conn.execute("""
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l
            ON a.lecture_id = l.id
            WHERE a.student_id = ?
        """, (student["id"],)).fetchone()[0]

        present = conn.execute("""
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l
            ON a.lecture_id = l.id
            WHERE a.student_id = ?
            AND a.status = 'P'
        """, (student["id"],)).fetchone()[0]

        percentage = 0

        if total:
            percentage = round(
                present * 100 / total,
                2
            )

        report.append({
            "id": student["id"],
            "roll_no": student["roll_no"],
            "prn": student["prn"],
            "name": student["name"],
            "total": total,
            "present": present,
            "absent": total - present,
            "percentage": percentage
        })

    conn.close()

    return render_template(
        "reports.html",
        report=report,
        subjects=subjects
    )


# --------------------------------------------------
# CSV EXPORT
# --------------------------------------------------

@app.route("/reports/export")
@login_required
def export_report():

    conn = get_db()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        ORDER BY CAST(roll_no AS INTEGER), name
    """).fetchall()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Roll No",
        "PRN",
        "Student Name",
        "Total Lectures",
        "Present",
        "Absent",
        "Attendance %"
    ])

    for student in students:

        total = conn.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE student_id = ?
        """, 
    (student["id"],)).fetchone()[0]

        present = conn.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE student_id = ?
            AND status = 'P'
        """, 
    (student["id"],)).fetchone()[0]

        absent = total - present

        percentage = 0

        if total:
            percentage = round(
                present * 100 / total,
                2
            )

        writer.writerow([
            student["roll_no"],
            student["prn"],
            student["name"],
            total,
            present,
            absent,
            percentage
        ])

    conn.close()

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
    "Content-Disposition":
                "attachment; "
    "filename=attendance_report.csv"
        }
    )

# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

init_db()

if __name__ == "__main__":
    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )
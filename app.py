from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, Response
)
import sqlite3
import csv
import io
import shutil
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATABASE = os.environ.get("DATABASE_PATH", "attendance.db")


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    bundled_database = "attendance.db"
    if DATABASE != bundled_database and not os.path.exists(DATABASE):
        if os.path.exists(bundled_database):
            os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
            shutil.copyfile(bundled_database, DATABASE)

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
        code TEXT NOT NULL UNIQUE,
        professor_name TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS lectures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        lecture_date TEXT NOT NULL,
        lecture_number INTEGER NOT NULL,
        division_scope TEXT DEFAULT '',
        locked INTEGER DEFAULT 0,
        UNIQUE(subject_id, lecture_date, lecture_number, division_scope),
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

    lecture_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(lectures)").fetchall()
    }
    if "division_scope" not in lecture_columns:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
            CREATE TABLE lectures_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                lecture_date TEXT NOT NULL,
                lecture_number INTEGER NOT NULL,
                division_scope TEXT DEFAULT '',
                locked INTEGER DEFAULT 0,
                UNIQUE(subject_id, lecture_date, lecture_number, division_scope),
                FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO lectures_new
            (id, subject_id, lecture_date, lecture_number, locked)
            SELECT id, subject_id, lecture_date, lecture_number, locked
            FROM lectures
        """)
        conn.execute("DROP TABLE lectures")
        conn.execute("ALTER TABLE lectures_new RENAME TO lectures")
        conn.execute("PRAGMA foreign_keys = ON")

    subject_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(subjects)").fetchall()
    }
    if "professor_name" not in subject_columns:
        conn.execute("ALTER TABLE subjects ADD COLUMN professor_name TEXT DEFAULT ''")

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


@app.route("/students/import", methods=["POST"])
@login_required
def import_students():

    uploaded_file = request.files.get("student_file")

    if not uploaded_file or not uploaded_file.filename:
        flash("Choose a CSV file to import.", "danger")
        return redirect(url_for("students"))

    try:
        content = uploaded_file.stream.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        required_columns = {"roll_no", "prn", "name"}
        columns = {
            column.strip().lower()
            for column in (reader.fieldnames or [])
            if column
        }

        if not required_columns.issubset(columns):
            flash(
                "CSV must include roll_no, prn and name columns.",
                "danger"
            )
            return redirect(url_for("students"))

        rows = list(reader)

        if not rows:
            flash("The CSV file does not contain any students.", "danger")
            return redirect(url_for("students"))

        if len(rows) > 100:
            flash("You can import a maximum of 100 students at a time.", "danger")
            return redirect(url_for("students"))

        conn = get_db()
        added = 0
        skipped = 0
        invalid = 0

        try:
            for row in rows:
                normalized_row = {
                    (key or "").strip().lower(): (value or "").strip()
                    for key, value in row.items()
                }
                roll_no = normalized_row.get("roll_no", "")
                prn = normalized_row.get("prn", "")
                name = normalized_row.get("name", "")

                if not roll_no or not prn or not name:
                    invalid += 1
                    continue

                try:
                    conn.execute(
                        """
                        INSERT INTO students
                        (roll_no, prn, name, class_name, division)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            roll_no,
                            prn,
                            name,
                            normalized_row.get("class_name", ""),
                            normalized_row.get("division", "")
                        )
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1

            conn.commit()
        finally:
            conn.close()

        summary = f"Imported {added} student(s)."
        if skipped:
            summary += f" Skipped {skipped} duplicate PRN(s)."
        if invalid:
            summary += f" Skipped {invalid} incomplete row(s)."
        flash(summary, "success" if added else "danger")

    except (UnicodeDecodeError, csv.Error):
        flash("The uploaded file is not a valid UTF-8 CSV file.", "danger")

    return redirect(url_for("students"))


@app.route("/students/sample.csv")
@login_required
def student_import_sample():

    sample = "roll_no,prn,name,class_name,division\n1,PRN123456,Student Name,B.Tech CSE,A\n"
    return Response(
        sample,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_sample.csv"}
    )


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
    professor_name = request.form.get("professor_name", "").strip()

    if not name or not code:
        flash("Subject name and code are required.", "danger")
        return redirect(url_for("subjects"))

    conn = get_db()

    try:

        conn.execute("""
            INSERT INTO subjects(name, code, professor_name)
            VALUES (?, ?, ?)
        """, (name, code, professor_name))

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

    selected_division = request.args.get("division", "").strip()
    conn = get_db()

    subjects = conn.execute(
        "SELECT * FROM subjects ORDER BY name"
    ).fetchall()

    divisions = conn.execute("""
        SELECT DISTINCT division
        FROM students
        WHERE active = 1 AND TRIM(division) != ''
        ORDER BY division
    """).fetchall()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        AND (? = '' OR division = ?)
        ORDER BY CAST(roll_no AS INTEGER), name
    """, (selected_division, selected_division)).fetchall()

    conn.close()

    return render_template(
        "attendence.html",
        subjects=subjects,
        students=students,
        divisions=divisions,
        selected_division=selected_division,
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
    division_scope = (data.get("division_scope") or "").strip()

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
        AND division_scope = ?
    """, (
        subject_id,
        lecture_date,
        lecture_number
        , division_scope
    )).fetchone()

    if lecture:

        lecture_id = lecture["id"]

    else:

        try:

            cursor = conn.execute("""
                INSERT INTO lectures
                (subject_id, lecture_date, lecture_number, division_scope)
                VALUES (?, ?, ?, ?)
            """, (
                subject_id,
                lecture_date,
                lecture_number,
                division_scope
            ))

            lecture_id = cursor.lastrowid

            conn.commit()

        except sqlite3.IntegrityError:

            conn.rollback()

            lecture = conn.execute("""
                SELECT *
                FROM lectures
                WHERE subject_id = ?
                AND lecture_date = ?
                AND lecture_number = ?
                AND division_scope = ?
            """, (
                subject_id,
                lecture_date,
                lecture_number,
                division_scope
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
        "division_scope": lecture["division_scope"],
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

    division_scope = lecture["division_scope"]
    active_students = conn.execute("""
        SELECT id
        FROM students
        WHERE active = 1
        AND (? = '' OR division = ?)
    """, (division_scope, division_scope)).fetchall()
    active_student_ids = {str(student["id"]) for student in active_students}
    submitted_student_ids = set(records)

    if submitted_student_ids != active_student_ids or any(
        records.get(student_id) not in ["P", "A"]
        for student_id in active_student_ids
    ):
        conn.close()
        return jsonify({
            "success": False,
            "message": "Mark Present or Absent for every student before saving."
        }), 400

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

    if not lecture["locked"]:
        division_scope = lecture["division_scope"]
        active_students = conn.execute("""
            SELECT id
            FROM students
            WHERE active = 1
            AND (? = '' OR division = ?)
        """, (division_scope, division_scope)).fetchall()
        marked_students = conn.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE lecture_id = ?
        """, (lecture_id,)).fetchone()[0]
        if marked_students != len(active_students):
            conn.close()
            return jsonify({
                "success": False,
                "message": "Save attendance for every student before proceeding."
            }), 400

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

def build_attendance_report(
    start_date=None, end_date=None, subject_id=None, division=None
):

    conn = get_db()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        ORDER BY CAST(roll_no AS INTEGER), name
    """).fetchall()

    date_filter = ""
    date_params = []
    if start_date:
        date_filter += " AND l.lecture_date >= ?"
        date_params.append(start_date)
    if end_date:
        date_filter += " AND l.lecture_date <= ?"
        date_params.append(end_date)
    if subject_id:
        date_filter += " AND l.subject_id = ?"
        date_params.append(subject_id)
    if division:
        students = [
            student for student in students
            if student["division"] == division
        ]

    report = []

    for student in students:

        total = conn.execute(f"""
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l ON a.lecture_id = l.id
            WHERE a.student_id = ?{date_filter}
        """, [student["id"], *date_params]).fetchone()[0]

        present = conn.execute(f"""
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l ON a.lecture_id = l.id
            WHERE a.student_id = ?
            AND a.status = 'P'{date_filter}
        """, [student["id"], *date_params]).fetchone()[0]

        report.append({
            "id": student["id"],
            "roll_no": student["roll_no"],
            "prn": student["prn"],
            "name": student["name"],
            "total": total,
            "present": present,
            "absent": total - present,
            "percentage": round(present * 100 / total, 2) if total else 0
        })

    conn.close()
    return report


@app.route("/reports")
@login_required
def reports():

    conn = get_db()

    subjects = conn.execute("""
        SELECT *
        FROM subjects
        ORDER BY name
    """).fetchall()

    subject_id = request.args.get("subject_id", type=int)
    division = request.args.get("division", "").strip()
    divisions = conn.execute("""
        SELECT DISTINCT division
        FROM students
        WHERE active = 1 AND TRIM(division) != ''
        ORDER BY division
    """).fetchall()
    conn.close()
    selected_subject = next(
        (subject for subject in subjects if subject["id"] == subject_id),
        None
    )

    return render_template(
        "reports.html",
        report=build_attendance_report(subject_id=subject_id, division=division),
        report_title=(
            f"{selected_subject['name']} Attendance"
            if selected_subject else "Overall Attendance"
        ),
        report_period=(
            f"All recorded lectures for {selected_subject['name']}"
            if selected_subject else "All recorded lectures across all subjects"
        ),
        subjects=subjects,
        selected_subject_id=subject_id,
        divisions=divisions,
        selected_division=division
    )


@app.route("/reports/<period>")
@login_required
def period_report(period):

    subject_id = request.args.get("subject_id", type=int)
    division = request.args.get("division", "").strip()

    today = date.today()
    if period == "weekly":
        start_date = today - timedelta(days=today.weekday())
        report_title = "Weekly Attendance"
        report_period = f"{start_date.isoformat()} to {today.isoformat()}"
    elif period == "monthly":
        start_date = today.replace(day=1)
        report_title = "Monthly Attendance"
        report_period = f"{start_date.isoformat()} to {today.isoformat()}"
    else:
        return redirect(url_for("reports"))

    conn = get_db()
    subjects = conn.execute(
        "SELECT * FROM subjects ORDER BY name"
    ).fetchall()
    divisions = conn.execute("""
        SELECT DISTINCT division
        FROM students
        WHERE active = 1 AND TRIM(division) != ''
        ORDER BY division
    """).fetchall()
    conn.close()

    selected_subject = next(
        (subject for subject in subjects if subject["id"] == subject_id),
        None
    )

    return render_template(
        "reports.html",
        report=build_attendance_report(
            start_date.isoformat(), today.isoformat(), subject_id
            , division
        ),
        report_title=(
            f"{selected_subject['name']} {report_title}"
            if selected_subject else f"Overall {report_title}"
        ),
        report_period=report_period,
        subjects=subjects,
        selected_subject_id=subject_id,
        divisions=divisions,
        selected_division=division
    )


# --------------------------------------------------
# CSV EXPORT
# --------------------------------------------------

@app.route("/reports/export")
@login_required
def export_report():

    conn = get_db()
    subject_id = request.args.get("subject_id", type=int)
    division = request.args.get("division", "").strip()
    period = request.args.get("period", "").strip()
    today = date.today()
    start_date = None
    end_date = None
    if period == "weekly":
        start_date = today - timedelta(days=today.weekday())
    elif period == "monthly":
        start_date = today.replace(day=1)
    if start_date:
        start_date = start_date.isoformat()
        end_date = today.isoformat()

    students = conn.execute("""
        SELECT *
        FROM students
        WHERE active = 1
        AND (? = '' OR division = ?)
        ORDER BY CAST(roll_no AS INTEGER), name
    """, (division, division)).fetchall()

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

        total_query = """
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l ON a.lecture_id = l.id
            WHERE a.student_id = ?
        """
        total_params = [student["id"]]
        if subject_id:
            total_query += " AND l.subject_id = ?"
            total_params.append(subject_id)
        if start_date:
            total_query += " AND l.lecture_date >= ? AND l.lecture_date <= ?"
            total_params.extend([start_date, end_date])
        total = conn.execute(total_query, total_params).fetchone()[0]

        present_query = """
            SELECT COUNT(*)
            FROM attendance a
            JOIN lectures l ON a.lecture_id = l.id
            WHERE a.student_id = ?
            AND a.status = 'P'
        """
        present_params = [student["id"]]
        if subject_id:
            present_query += " AND l.subject_id = ?"
            present_params.append(subject_id)
        if start_date:
            present_query += " AND l.lecture_date >= ? AND l.lecture_date <= ?"
            present_params.extend([start_date, end_date])
        present = conn.execute(present_query, present_params).fetchone()[0]

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
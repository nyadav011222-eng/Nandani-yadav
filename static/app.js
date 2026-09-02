let currentLectureId = null;
let currentLocked = false;


// ---------------------------------------
// LOAD LECTURE
// ---------------------------------------

async function loadLecture() {

    const subject = document.getElementById("subject").value;
    const lectureDate = document.getElementById("lecture-date").value;
    const lectureNumber =
        document.getElementById("lecture-number").value;

    if (!subject || !lectureDate || !lectureNumber) {

        alert("Please select subject, date and lecture number.");

        return;
    }

    try {

        const response = await fetch("/api/lecture", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({

                subject_id: subject,
                lecture_date: lectureDate,
                lecture_number: lectureNumber

            })

        });

        const data = await response.json();

        if (!data.success) {

            alert(data.message);

            return;
        }

        currentLectureId = data.lecture_id;
        currentLocked = data.locked;

        document
            .getElementById("attendance-area")
            .classList.remove("hidden");

        updateAttendanceButtons(data.attendance);

        updateLockStatus();

    } catch (error) {

        console.error(error);

        alert("Something went wrong.");

    }
}


// ---------------------------------------
// UPDATE ATTENDANCE BUTTONS
// ---------------------------------------

function updateAttendanceButtons(attendance) {

    const rows =
        document.querySelectorAll(
            "#attendance-body tr"
        );

    rows.forEach(row => {

        const studentId =
            row.dataset.studentId;

        const status =
            attendance[studentId] || "A";

        setRowStatus(row, status);

    });

}


// ---------------------------------------
// TOGGLE
// ---------------------------------------

function setStudentAttendance(button, status) {

    if (currentLocked) {

        alert("Attendance is locked.");

        return;
    }

    setRowStatus(button.closest("tr"), status);

}


// ---------------------------------------
// SET BUTTON STATUS
// ---------------------------------------

function setRowStatus(row, status) {

    row.querySelectorAll(".attendance-btn").forEach(button => {
        const selected = button.dataset.status === status;
        button.classList.toggle("selected", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
    });


}


// ---------------------------------------
// MARK ALL
// ---------------------------------------

function markAll(status) {

    if (currentLocked) {

        alert("Attendance is locked.");

        return;
    }

    const buttons =
        document.querySelectorAll(
            ".attendance-btn.present"
        );

    buttons.forEach(button => {

        setRowStatus(button.closest("tr"), status);

    });

}


// ---------------------------------------
// SAVE ATTENDANCE
// ---------------------------------------

async function saveAttendance() {

    if (!currentLectureId) {

        alert("Please load a lecture first.");

        return;
    }

    if (currentLocked) {

        alert("Attendance is locked.");

        return;
    }

    const records = {};

    const rows =
        document.querySelectorAll(
            "#attendance-body tr"
        );

    rows.forEach(row => {

        const studentId =
            row.dataset.studentId;

        const selectedButton =
            row.querySelector(".attendance-btn.selected");

        records[studentId] =
            selectedButton ? selectedButton.dataset.status : "A";

    });


    try {

        const response = await fetch(
            "/api/attendance/save",
            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    lecture_id:
                        currentLectureId,

                    records: records

                })

            }
        );

        const data =
            await response.json();

        if (data.success) {

            alert(
                "Attendance saved successfully."
            );

        } else {

            alert(data.message);

        }

    } catch (error) {

        console.error(error);

        alert(
            "Unable to save attendance."
        );

    }

}


// ---------------------------------------
// LOCK / UNLOCK
// ---------------------------------------

async function toggleLectureLock() {

    if (!currentLectureId) {

        alert("Load a lecture first.");

        return;
    }

    try {

        const response = await fetch(
            `/api/lecture/${currentLectureId}/lock`,
            {
                method: "POST"
            }
        );

        const data =
            await response.json();

        if (data.success) {

            currentLocked = data.locked;

            updateLockStatus();

        } else {

            alert(data.message);

        }

    } catch (error) {

        console.error(error);

        alert(
            "Unable to change lock status."
        );

    }

}


// ---------------------------------------
// LOCK STATUS
// ---------------------------------------

function updateLockStatus() {

    const element =
        document.getElementById(
            "lock-status"
        );

    if (!element) {
        return;
    }

    if (currentLocked) {

        element.innerHTML =
            '<div class="alert danger">🔒 Attendance is LOCKED</div>';

    } else {

        element.innerHTML =
            '<div class="alert success">🔓 Attendance is UNLOCKED</div>';

    }

}


// ---------------------------------------
// CONFIRM DELETE
// ---------------------------------------

function confirmDelete(message) {

    return confirm(
        message || "Are you sure?"
    );

}
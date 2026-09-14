"""Selectors and URL fragments for Talenta's attendance request modal.

Values come from the saved attendance page and Talenta's
scriptEmployeeAttendance.js. If Talenta changes its layout, fix it here.
"""

LOGIN_HOST = "account.mekari.com"

REQUEST_BUTTON = "#changeShiftRequestBtn"
MODAL = "#modalReqAttendance"

ATTENDANCE_RADIO = "#typeRequestCheckin"
ATTENDANCE_RADIO_LABEL = 'label[for="typeRequestCheckin"]'

EFFECTIVE_DATE = "#datepicker_request"
EFFECTIVE_DATE_HIDDEN = 'input[name="datepicker_request_submit"]'

SHIFT_SELECT = "#checkinrequest-shift_id"

CHECKIN_BOX = "#checkInBox"
CHECKOUT_BOX = "#checkOutBox"
CHECKIN_TIME = "#checkInAttendance"
CHECKOUT_TIME = "#checkOutAttendance"
CHECKIN_DATE_SELECT = "#checkInDateAttendance"
CHECKOUT_DATE_SELECT = "#checkOutDateAttendance"

NOTES = "#changeshiftrequest-reason"

SUBMIT_BUTTON = "#btnSaveRequest"
CANCEL_BUTTON = "#modalReqAttendance .custom-cancel-btn"

TOAST = "#toast-container .toast"

SHIFT_LOOKUP_PATH = "/attendance/get-current-shift"
SAVE_REQUEST_PATH = "/attendance/save-request"

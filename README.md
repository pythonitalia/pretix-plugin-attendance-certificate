# pretix-plugin-attendance-certificate

A [pretix](https://pretix.eu) plugin to design certificates of attendance and
send them to attendees by email, either manually or automatically after they
check in.

Used by [PyCon Italia](https://pycon.it).

## Features

- **Certificate editor:** design the certificate in the pretix PDF editor,
  with your own background PDF and attendee and event fields.
- **Bulk sending:** send the certificate to all attendees with a paid
  admission ticket from the pretix "Send out emails" page.
- **Per-attendee actions:** download or email the certificate from the order
  page.
- **Automatic sending after check-in** (optional, per event): an attendee
  receives the certificate as soon as they check in.
- **No duplicate emails:** the automatic email goes out at most once per
  attendee, even if they check in several times.
- **Delivery history:** see every certificate that was sent, which ones
  failed and why, and send it again.

## Installation

Install the plugin in the Python environment of your pretix installation:

```bash
pip install pretix-plugin-attendance-certificate
```

Apply the database migrations and restart pretix (web server and Celery
workers):

```bash
python -m pretix migrate
```

Then enable **Attendance Certificate** in the event under
*Settings → Plugins*.

## Usage

Once the plugin is enabled, the event menu shows a **Certificate of
Attendance** section with these pages:

| Page | What it does |
| --- | --- |
| Editor | Design the certificate layout and upload a background PDF. |
| Send out certificates | Email the certificate to all attendees with a paid admission ticket. |
| Delivery history | List every delivery with its status, and resend it. |
| Settings | Turn automatic sending on or off and edit the email text. |

### Designing the certificate

Open *Certificate of Attendance → Editor*. Upload a background PDF and place
fields such as the attendee name on it. To check the result, use the
**Certificate of attendance** button next to a ticket on any order page, which
downloads the PDF for that attendee.

### Sending certificates manually

- **To everyone:** *Certificate of Attendance → Send out certificates* uses
  the pretix email form, so you can write the subject and message and use the
  usual email placeholders.
- **To one attendee:** on the order page, click **Email certificate of
  attendance** next to the ticket. This button is shown only when the ticket
  has an attendee email.

A certificate is only sent to attendees whose last successful check-in is an
entry. Attendees who never checked in, or whose last scan was an exit, are
skipped, and this is noted in the order history.

### Sending certificates automatically after check-in

Automatic sending is **off by default**. To turn it on, open
*Certificate of Attendance → Settings* (also listed under the event
*Settings* menu) and check **Send certificates automatically after check-in**.

When it is on, this is what happens:

1. An attendee checks in at the entrance.
2. pretix sends its `checkin_created` signal, and the plugin receives it.
3. After the check-in is saved, the plugin queues a Celery task.
4. The task checks that the attendee is present, the order is paid, the
   ticket is not canceled and there is an email address. It uses the attendee
   email, or the order email if the ticket has none.
5. The certificate PDF is generated and attached to the email.

Each attendee receives the automatic email **only once**. Checking in again
does not send another certificate. If an automatic send failed, the next
check-in tries again. Sending manually from the order page always sends the
certificate, even if it was sent before.

The same settings page has the **email subject** and **email text**, with one
field for each language of the event. Placeholders such as `{event}` are
replaced. These texts are used for automatic sending and for the button on the
order page. The default text is in English.

Automatic sending needs a running Celery worker, which a standard pretix
installation already has.

### Delivery history

*Certificate of Attendance → Delivery history* lists every certificate that
has been sent for the event. For each one it shows:

- order and attendee
- recipient email
- status: **Sending**, **Sent** or **Failed**
- the error message, if it failed
- whether it was sent automatically after check-in or manually
- when it was last tried and when it was sent

You can filter the list by status and send a certificate again from there.
Each order's history also records when a certificate was sent, when sending
failed and when an automatic email was skipped because it had already been
sent.

**Sent** means the email was handed over to pretix's email queue. If the mail
server rejects it later, pretix records that error in the order history.

### Permissions

| Action | Required permission |
| --- | --- |
| View the delivery history, download certificates | View orders |
| Email a certificate from the order page, resend from the history | Change orders |
| Change the plugin settings | Change event settings |

## Development

The plugin is developed and tested against **pretix 2026.8**. Create a
virtual environment, then install pretix, the test tools and the plugin in
editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install "pretix==2026.8.0" pytest pytest-django
pip install -e .
```

Run the tests:

```bash
pytest
```

Tests use pretix's test settings (`pretix.testutils.settings`, configured in
`setup.cfg`) with a SQLite database. No extra services are needed.

To work on the plugin in a real pretix instance, install it in editable mode
in that instance's environment, run `python -m pretix migrate` and restart
the web server and the Celery workers.

### Project layout

```text
pretix_attendance_certificate/
├── apps.py               # plugin metadata and signal registration
├── checkin_handlers.py   # queues the automatic send after a check-in
├── email_defaults.py     # default email texts and plugin settings
├── models.py             # certificate layout and delivery tracking
├── render.py             # renders the certificate PDF
├── signals.py            # menu entries, order page buttons, log messages
├── tasks.py              # Celery tasks that send the certificates
├── urls.py
├── views/
│   ├── deliveries.py     # delivery history page
│   ├── editor.py         # certificate layout editor
│   ├── emails.py         # bulk sending page
│   ├── positions.py      # download / email a single certificate
│   └── settings.py       # plugin settings page
└── templates/
```

## License

MIT, see [LICENSE](LICENSE).

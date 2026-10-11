=== TutorTrack Widgets ===
Contributors: tutortrack
Tags: tutoring, tutors, enquiry form, booking
Requires at least: 6.0
Tested up to: 6.6
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later

Embed your TutorTrack tutor directory, enquiry forms, services and prices, reviews, tutor vacancies and portal login.

== Installation ==

1. Upload the `tutortrack-widgets` folder to `/wp-content/plugins/` and activate it.
2. Settings → TutorTrack: enter your organisation (e.g. `brightminds`), and your portal address if you connected a custom domain.
3. In TutorTrack → Website & branding → Widgets, create a widget, add this site's address (e.g. `https://www.example.com`) to its allowed websites and copy its shortcode.
4. Paste the shortcode into a page or a Shortcode block, e.g. `[tutortrack widget="w-1a2b3c4d5e" type="tutor_directory"]`.

== Other site builders ==

Wix (Embed code → Embed HTML), Squarespace (Code block) and Webflow (Embed element): paste the embed code shown for the widget in TutorTrack. It is a `<script>` tag plus the widget element; the script can go once in the site-wide header instead.

== Shortcode attributes ==

* `type`: tutor_directory, enquiry_form, services, reviews, login or job_openings
* `widget`: the widget key from TutorTrack (applies its settings and theme)
* `form`: an enquiry form's address (enquiry_form)
* `portal`: client, tutor or staff (login)
* `enquire_url`: where the tutor directory's "Enquire" button goes

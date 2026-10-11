<?php
/**
 * Plugin Name:       TutorTrack Widgets
 * Description:       Embed your TutorTrack tutor directory, enquiry forms, services, reviews, vacancies and portal login with shortcodes.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            TutorTrack
 * License:           GPL-2.0-or-later
 * Text Domain:       tutortrack-widgets
 *
 * Usage (copy the shortcode from TutorTrack → Website & branding → Widgets):
 *   [tutortrack widget="w-1a2b3c4d5e" type="tutor_directory"]
 *   [tutortrack type="enquiry_form" form="enquire"]
 *   [tutortrack type="login" portal="tutor"]
 */

if (!defined('ABSPATH')) {
    exit;
}

const TUTORTRACK_ELEMENTS = array(
    'tutor_directory' => 'tt-tutor-directory',
    'enquiry_form'    => 'tt-enquiry-form',
    'services'        => 'tt-services',
    'reviews'         => 'tt-reviews',
    'login'           => 'tt-login',
    'job_openings'    => 'tt-job-openings',
);

function tutortrack_option($name, $default = '') {
    $value = get_option('tutortrack_' . $name, $default);
    return is_string($value) ? $value : $default;
}

/** One module script for every widget on the page, printed once in the footer. */
function tutortrack_enqueue_loader() {
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    add_action('wp_footer', function () {
        $src = tutortrack_option('script_url', 'https://cdn.tutortrack.app/widgets.js');
        printf(
            '<script type="module" src="%s" data-org="%s" data-api="%s" data-locale="%s"></script>',
            esc_url($src),
            esc_attr(tutortrack_option('organisation')),
            esc_url(tutortrack_option('api_url')),
            esc_attr(str_replace('_', '-', get_locale()))
        );
    });
}

function tutortrack_shortcode($atts) {
    $atts = shortcode_atts(
        array('type' => 'tutor_directory', 'widget' => '', 'form' => '', 'portal' => '', 'enquire_url' => ''),
        $atts,
        'tutortrack'
    );
    $type = sanitize_key($atts['type']);
    if (!isset(TUTORTRACK_ELEMENTS[$type])) {
        return '';
    }
    tutortrack_enqueue_loader();
    $element = TUTORTRACK_ELEMENTS[$type];
    $attributes = '';
    foreach (array('widget' => 'widget', 'form' => 'form', 'portal' => 'portal', 'enquire_url' => 'enquire-url') as $key => $attribute) {
        if ($atts[$key] !== '') {
            $attributes .= sprintf(' %s="%s"', $attribute, esc_attr($atts[$key]));
        }
    }
    return sprintf('<%1$s%2$s></%1$s>', $element, $attributes);
}
add_shortcode('tutortrack', 'tutortrack_shortcode');

/** Settings → TutorTrack: organisation slug, API address (custom domain) and script URL. */
add_action('admin_menu', function () {
    add_options_page('TutorTrack', 'TutorTrack', 'manage_options', 'tutortrack', 'tutortrack_settings_page');
});

add_action('admin_init', function () {
    foreach (array('organisation' => 'sanitize_key', 'api_url' => 'esc_url_raw', 'script_url' => 'esc_url_raw') as $name => $sanitize) {
        register_setting('tutortrack', 'tutortrack_' . $name, array('type' => 'string', 'sanitize_callback' => $sanitize));
    }
});

function tutortrack_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    ?>
    <div class="wrap">
        <h1><?php esc_html_e('TutorTrack', 'tutortrack-widgets'); ?></h1>
        <form method="post" action="options.php">
            <?php settings_fields('tutortrack'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="tutortrack_organisation"><?php esc_html_e('Organisation (your TutorTrack address, e.g. brightminds)', 'tutortrack-widgets'); ?></label></th>
                    <td><input id="tutortrack_organisation" name="tutortrack_organisation" class="regular-text" value="<?php echo esc_attr(tutortrack_option('organisation')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="tutortrack_api_url"><?php esc_html_e('Portal address if you use a custom domain (optional)', 'tutortrack-widgets'); ?></label></th>
                    <td><input id="tutortrack_api_url" name="tutortrack_api_url" type="url" class="regular-text" value="<?php echo esc_attr(tutortrack_option('api_url')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="tutortrack_script_url"><?php esc_html_e('Widget script URL', 'tutortrack-widgets'); ?></label></th>
                    <td><input id="tutortrack_script_url" name="tutortrack_script_url" type="url" class="regular-text" value="<?php echo esc_attr(tutortrack_option('script_url', 'https://cdn.tutortrack.app/widgets.js')); ?>"></td>
                </tr>
            </table>
            <p><?php esc_html_e('Add this website\'s address to the widget\'s allowed websites in TutorTrack.', 'tutortrack-widgets'); ?></p>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

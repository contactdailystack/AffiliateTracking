<?php
/**
 * Plugin Name: Affiliate Link Integrity Checker
 * Description: Syncs external affiliate links from WordPress posts into the integrity checker dashboard.
 * Version: 0.1.0
 * Author: Codex
 */

if (!defined('ABSPATH')) {
    exit;
}

final class Affiliate_Link_Integrity_Checker {
    const OPTION_KEY = 'affiliate_link_integrity_checker_settings';
    const NONCE_ACTION = 'affiliate_link_integrity_checker_sync';

    public static function init(): void {
        add_action('admin_menu', [__CLASS__, 'register_menu']);
        add_action('admin_init', [__CLASS__, 'register_settings']);
        add_action('add_meta_boxes', [__CLASS__, 'register_metabox']);
        add_action('save_post', [__CLASS__, 'handle_save_post'], 20, 2);
    }

    public static function defaults(): array {
        return [
            'api_base_url' => 'http://localhost:8000',
            'api_key' => '',
            'project_id' => '',
            'merchant_name' => 'WordPress',
            'auto_sync_enabled' => 1,
        ];
    }

    public static function settings(): array {
        return wp_parse_args(get_option(self::OPTION_KEY, []), self::defaults());
    }

    public static function register_menu(): void {
        add_options_page(
            'Affiliate Link Integrity Checker',
            'Affiliate Link Checker',
            'manage_options',
            'affiliate-link-integrity-checker',
            [__CLASS__, 'render_settings_page']
        );
    }

    public static function register_settings(): void {
        register_setting('affiliate_link_integrity_checker', self::OPTION_KEY, [__CLASS__, 'sanitize_settings']);
    }

    public static function sanitize_settings($input): array {
        $current = self::settings();
        return [
            'api_base_url' => esc_url_raw(trim($input['api_base_url'] ?? $current['api_base_url'])),
            'api_key' => sanitize_text_field($input['api_key'] ?? $current['api_key']),
            'project_id' => sanitize_text_field($input['project_id'] ?? $current['project_id']),
            'merchant_name' => sanitize_text_field($input['merchant_name'] ?? $current['merchant_name']),
            'auto_sync_enabled' => !empty($input['auto_sync_enabled']) ? 1 : 0,
        ];
    }

    public static function register_metabox(): void {
        add_meta_box(
            'affiliate-link-integrity-checker',
            'Affiliate Link Checker',
            [__CLASS__, 'render_metabox'],
            null,
            'side',
            'default'
        );
    }

    public static function render_settings_page(): void {
        if (!current_user_can('manage_options')) {
            return;
        }
        $settings = self::settings();
        ?>
        <div class="wrap">
            <h1>Affiliate Link Integrity Checker</h1>
            <form method="post" action="options.php">
                <?php settings_fields('affiliate_link_integrity_checker'); ?>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><label for="api_base_url">API Base URL</label></th>
                        <td><input name="<?php echo esc_attr(self::OPTION_KEY); ?>[api_base_url]" id="api_base_url" type="url" class="regular-text" value="<?php echo esc_attr($settings['api_base_url']); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="api_key">API Key</label></th>
                        <td><input name="<?php echo esc_attr(self::OPTION_KEY); ?>[api_key]" id="api_key" type="password" class="regular-text" value="<?php echo esc_attr($settings['api_key']); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="project_id">Project ID</label></th>
                        <td><input name="<?php echo esc_attr(self::OPTION_KEY); ?>[project_id]" id="project_id" type="text" class="regular-text" value="<?php echo esc_attr($settings['project_id']); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="merchant_name">Merchant Name</label></th>
                        <td><input name="<?php echo esc_attr(self::OPTION_KEY); ?>[merchant_name]" id="merchant_name" type="text" class="regular-text" value="<?php echo esc_attr($settings['merchant_name']); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row">Auto Sync</th>
                        <td><label><input name="<?php echo esc_attr(self::OPTION_KEY); ?>[auto_sync_enabled]" type="checkbox" value="1" <?php checked($settings['auto_sync_enabled'], 1); ?>> Sync external links when posts are saved</label></td>
                    </tr>
                </table>
                <?php submit_button('Save Settings'); ?>
            </form>
        </div>
        <?php
    }

    public static function render_metabox($post): void {
        $settings = self::settings();
        ?>
        <p><strong>Project:</strong> <?php echo esc_html($settings['project_id'] ?: 'Not configured'); ?></p>
        <p><strong>Merchant:</strong> <?php echo esc_html($settings['merchant_name']); ?></p>
        <p>Save the post to sync external links to the dashboard.</p>
        <?php
    }

    public static function handle_save_post(int $post_id, \WP_Post $post): void {
        if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
            return;
        }
        if (wp_is_post_revision($post_id)) {
            return;
        }
        if (!current_user_can('edit_post', $post_id)) {
            return;
        }

        $settings = self::settings();
        if (empty($settings['auto_sync_enabled']) || empty($settings['api_base_url']) || empty($settings['api_key']) || empty($settings['project_id'])) {
            return;
        }

        $links = self::extract_external_links($post->post_content, get_permalink($post_id));
        if (empty($links)) {
            return;
        }

        self::sync_links($settings, $links, $post->post_title);
    }

    private static function extract_external_links(string $content, string $site_url): array {
        if (empty($content)) {
            return [];
        }

        preg_match_all('/https?:\/\/[^\s"\'<>]+/i', $content, $matches);
        $raw = array_unique(array_map('esc_url_raw', $matches[0] ?? []));
        $site_host = wp_parse_url($site_url, PHP_URL_HOST);
        $results = [];

        foreach ($raw as $url) {
            $host = wp_parse_url($url, PHP_URL_HOST);
            if (!$host || !$site_host || strtolower($host) === strtolower($site_host)) {
                continue;
            }
            $results[] = [
                'merchant_name' => self::settings()['merchant_name'],
                'original_url' => $url,
                'source_label' => 'WordPress post',
            ];
        }

        return $results;
    }

    private static function sync_links(array $settings, array $links, string $title): void {
        $endpoint = trailingslashit(rtrim($settings['api_base_url'], '/')) . 'integrations/wordpress/sync-links';
        $response = wp_remote_post($endpoint, [
            'timeout' => 15,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-API-Key' => $settings['api_key'],
            ],
            'body' => wp_json_encode([
                'project_id' => $settings['project_id'],
                'merchant_name' => $settings['merchant_name'],
                'links' => $links,
            ]),
        ]);

        if (is_wp_error($response)) {
            error_log('Affiliate Link Checker sync failed: ' . $response->get_error_message());
            return;
        }

        $code = wp_remote_retrieve_response_code($response);
        if ($code >= 400) {
            error_log('Affiliate Link Checker sync failed for "' . $title . '": HTTP ' . $code);
        }
    }
}

Affiliate_Link_Integrity_Checker::init();

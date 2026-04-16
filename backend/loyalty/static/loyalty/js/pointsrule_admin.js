(function($) {
    'use strict';

    // Field visibility configuration per rule type
    const fieldConfig = {
        'per_euro': {
            points: { show: false, hint: 'Not used for this rule type' },
            multiplier: { show: true, hint: 'Formula: order total × multiplier = points. E.g., 0.1 = 1 point per €10 spent, 1 = 1 point per €1' },
            condition_value: { show: false, hint: 'Not used for this rule type' }
        },
        'per_order': {
            points: { show: true, hint: 'Fixed points awarded for each order' },
            multiplier: { show: false, hint: 'Not used for this rule type' },
            condition_value: { show: false, hint: 'Not used for this rule type' }
        },
        'product_sku': {
            points: { show: true, hint: 'Points awarded per item with matching SKU' },
            multiplier: { show: false, hint: 'Not used for this rule type' },
            condition_value: { show: true, hint: 'Enter the exact product SKU from Shopify' }
        },
        'product_title': {
            points: { show: true, hint: 'Points awarded per matching product' },
            multiplier: { show: false, hint: 'Not used for this rule type' },
            condition_value: { show: true, hint: 'Enter keyword to match in product title (case-insensitive)' }
        },
        'minimum_order': {
            points: { show: true, hint: 'Bonus points awarded when minimum is met' },
            multiplier: { show: false, hint: 'Not used for this rule type' },
            condition_value: { show: true, hint: 'Minimum order value in euros (e.g., 50)' }
        },
        'first_order': {
            points: { show: true, hint: 'Welcome bonus points for new customers' },
            multiplier: { show: false, hint: 'Not used for this rule type' },
            condition_value: { show: false, hint: 'Not used for this rule type' }
        }
    };

    function updateFieldVisibility(ruleType) {
        const config = fieldConfig[ruleType];
        if (!config) return;

        // Update each field
        ['points', 'multiplier', 'condition_value'].forEach(function(fieldName) {
            const fieldRow = $('.form-row.field-' + fieldName);
            const fieldConfig = config[fieldName];

            if (fieldRow.length) {
                if (fieldConfig.show) {
                    fieldRow.show();
                    fieldRow.removeClass('field-hidden');
                } else {
                    fieldRow.hide();
                    fieldRow.addClass('field-hidden');
                }

                // Update help text
                const helpText = fieldRow.find('.help');
                if (helpText.length) {
                    if (!fieldConfig.show) {
                        helpText.html('<em style="color: #999;">' + fieldConfig.hint + '</em>');
                    } else {
                        helpText.html('<strong style="color: #17a2b8;">' + fieldConfig.hint + '</strong>');
                    }
                }
            }
        });

        // Update live preview
        updateLivePreview();
    }

    function updateLivePreview() {
        const ruleType = $('#id_rule_type').val();
        const ruleName = $('#id_name').val() || 'This rule';
        const points = parseInt($('#id_points').val()) || 0;
        const multiplier = parseFloat($('#id_multiplier').val()) || 0;
        const conditionValue = $('#id_condition_value').val() || '';

        let previewHtml = '';
        let previewClass = 'preview-info';

        switch(ruleType) {
            case 'per_euro':
                if (multiplier > 0) {
                    // Calculate examples using actual formula: order_total * multiplier
                    const pts25 = Math.floor(25 * multiplier);
                    const pts50 = Math.floor(50 * multiplier);
                    const pts100 = Math.floor(100 * multiplier);
                    const eurosPerPoint = 1 / multiplier;

                    let explanation;
                    if (eurosPerPoint === Math.floor(eurosPerPoint)) {
                        explanation = `<strong>1 point for every €${Math.floor(eurosPerPoint)} spent</strong>`;
                    } else {
                        explanation = `<strong>${multiplier} points for every €1 spent</strong>`;
                    }

                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award ${explanation}.<br><br>
                        <span style="color: #666;">Formula: order total × ${multiplier} = points</span><br><br>
                        <strong>Examples:</strong><br>
                        • €25 order → ${pts25} points<br>
                        • €50 order → ${pts50} points<br>
                        • €100 order → ${pts100} points
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set the <strong>Multiplier</strong> field. Formula: order total × multiplier = points.<br><span style="color: #666;">E.g., 0.1 = 1 point per €10 spent</span>';
                }
                break;

            case 'per_order':
                if (points > 0) {
                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award <strong>${points} points</strong> for every order.<br>
                        <span style="color: #666;">This is a flat bonus regardless of order value.</span>
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set the <strong>Points</strong> field to define the bonus per order.';
                }
                break;

            case 'product_sku':
                if (points > 0 && conditionValue) {
                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award <strong>${points} points</strong> for each product with SKU "<strong>${conditionValue}</strong>".<br>
                        <span style="color: #666;">Buying 3 items = ${points * 3} points.</span>
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set both <strong>Points</strong> and <strong>Condition value</strong> (SKU) fields.';
                }
                break;

            case 'product_title':
                if (points > 0 && conditionValue) {
                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award <strong>${points} points</strong> for products containing "<strong>${conditionValue}</strong>" in the title.<br>
                        <span style="color: #666;">Matches are case-insensitive.</span>
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set both <strong>Points</strong> and <strong>Condition value</strong> (keyword) fields.';
                }
                break;

            case 'minimum_order':
                if (points > 0 && conditionValue) {
                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award <strong>${points} bonus points</strong> when order total is <strong>€${conditionValue} or more</strong>.<br>
                        <span style="color: #666;">This is a one-time bonus per qualifying order.</span>
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set both <strong>Points</strong> (bonus) and <strong>Condition value</strong> (minimum euros) fields.';
                }
                break;

            case 'first_order':
                if (points > 0) {
                    previewHtml = `
                        <strong>"${ruleName}"</strong> will award <strong>${points} welcome points</strong> on a customer's first order.<br>
                        <span style="color: #666;">Only applies once per customer, for their very first purchase.</span>
                    `;
                    previewClass = 'preview-success';
                } else {
                    previewHtml = 'Set the <strong>Points</strong> field to define the welcome bonus.';
                }
                break;

            default:
                previewHtml = 'Select a <strong>Rule type</strong> above to see the preview.';
        }

        // Update or create the live preview box
        let previewBox = $('#live-preview-box');
        if (!previewBox.length) {
            // Create preview box after the Points Configuration fieldset
            const configFieldset = $('fieldset:contains("Points Configuration")');
            if (configFieldset.length) {
                configFieldset.after(`
                    <fieldset class="module aligned" id="live-preview-fieldset">
                        <h2>Live Preview</h2>
                        <div id="live-preview-box" class="preview-box"></div>
                    </fieldset>
                `);
                previewBox = $('#live-preview-box');
            }
        }

        if (previewBox.length) {
            previewBox.html(previewHtml);
            previewBox.removeClass('preview-info preview-success preview-warning');
            previewBox.addClass(previewClass);
        }
    }

    function addCustomStyles() {
        const styles = `
            <style>
                .field-hidden .help {
                    font-style: italic;
                    color: #999 !important;
                }
                #live-preview-fieldset {
                    margin-top: 0;
                }
                .preview-box {
                    padding: 15px;
                    border-radius: 8px;
                    line-height: 1.6;
                }
                .preview-info {
                    background: #e7f3ff;
                    border-left: 4px solid #17a2b8;
                }
                .preview-success {
                    background: #d4edda;
                    border-left: 4px solid #28a745;
                }
                .preview-warning {
                    background: #fff3cd;
                    border-left: 4px solid #ffc107;
                }
                .form-row.field-hidden {
                    opacity: 0.5;
                }
            </style>
        `;
        $('head').append(styles);
    }

    $(document).ready(function() {
        // Only run on PointsRule add/change pages
        if (!$('#id_rule_type').length) return;

        addCustomStyles();

        // Initial setup
        const initialRuleType = $('#id_rule_type').val();
        if (initialRuleType) {
            updateFieldVisibility(initialRuleType);
        }

        // Listen for rule type changes
        $('#id_rule_type').on('change', function() {
            updateFieldVisibility($(this).val());
        });

        // Listen for changes to update live preview
        $('#id_name, #id_points, #id_multiplier, #id_condition_value').on('input change', function() {
            updateLivePreview();
        });

        // Trigger initial preview
        updateLivePreview();
    });

})(django.jQuery);

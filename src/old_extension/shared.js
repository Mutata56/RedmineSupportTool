/**
 * @fileoverview Shared utilities and configuration for <название> Ticket Management Browser Extension
 * @description Centralized storage management, theme controls, and shift formatting utilities
 * @version 2.0.0
 * @author KKRLL56
 */

'use strict';

// ============================================================================
// CONFIGURATION CONSTANTS
// ============================================================================

/**
 * Storage configuration keys for extension settings
 * @readonly
 * @enum {string}
 */
const STORAGE_CONFIG = {
    DASHBOARD_ENABLED: '_ticketDashboardEnabled',
    AUTO_SYNC_ENABLED: '_ticketAutoSyncEnabled',
    DARK_MODE: '_ticketShiftDarkMode',
    SHIFT_STORAGE: '_ticketShiftStorage',
    FONT_SCROLLER_ENABLED: '_ticketFontScrollerEnabled',
    DASHBOARD_MONITORING: '_dashboardMonitoringEnabled'
};

/**
 * Ticket category definitions with Russian labels
 * @readonly
 * @enum {string}
 */
const TICKET_CATEGORIES = {
    IN_PROGRESS: 'В работе',
    WAITING_CLIENT: 'Ожидание ответа от клиента',
    RESOLVED: 'Решена',
    NEW: 'Новая',
    NO_TIME_SPENT: 'Нет трудозатрат',
    NO_REASON: 'Нет причины обращения'
};

/**
 * Default shift structure with empty arrays for each category
 * @readonly
 * @type {Object<string, Array>}
 */
const DEFAULT_SHIFT_STRUCTURE = {
    [TICKET_CATEGORIES.IN_PROGRESS]: [],
    [TICKET_CATEGORIES.WAITING_CLIENT]: [],
    [TICKET_CATEGORIES.RESOLVED]: [],
    [TICKET_CATEGORIES.NEW]: [],
    [TICKET_CATEGORIES.NO_TIME_SPENT]: [],
    [TICKET_CATEGORIES.NO_REASON]: []
};

/**
 * SQL copy button configuration
 * @readonly
 */
const SQL_COPY_CONFIG = {
    SELECTOR: 'pre > code.sql.syntaxhl',
    CLASS_NAME: 'sql-copy-btn',
    ICONS: {
        COPY: '📋',
        SUCCESS: '✅'
    },
    FEEDBACK_DURATION: 1500,
    MONITOR_INTERVAL: 1500
};

/**
 * Console logging messages for debugging
 * @readonly
 */
const LOG_MESSAGES = {
    DARK_MODE_TOGGLE: 'Dark mode toggled to:',
    SHIFT_CLEARED: 'Смена очищена',
    SQL_BUTTON_ADDED: 'SQL copy button added',
    STORAGE_ERROR: 'Storage operation failed:'
};

// ============================================================================
// CORE STORAGE UTILITIES
// ============================================================================

/**
 * Retrieves the current shift data from localStorage with fallback to default structure
 * @returns {Object<string, Array>} The shift data organized by categories
 * @throws {Error} If localStorage is unavailable or data is corrupted
 */
function getStoredShift() {
    try {
        const storedData = localStorage.getItem(STORAGE_CONFIG.SHIFT_STORAGE);
        if (!storedData) {
            return { ...DEFAULT_SHIFT_STRUCTURE };
        }
        
        const parsedData = JSON.parse(storedData);
        
        // Ensure all required categories exist
        const result = { ...DEFAULT_SHIFT_STRUCTURE };
        Object.keys(parsedData).forEach(key => {
            if (result.hasOwnProperty(key) && Array.isArray(parsedData[key])) {
                result[key] = parsedData[key];
            }
        });
        
        return result;
    } catch (error) {
        console.error(LOG_MESSAGES.STORAGE_ERROR, error);
        return { ...DEFAULT_SHIFT_STRUCTURE };
    }
}

/**
 * Persists shift data to localStorage with error handling
 * @param {Object<string, Array>} shiftData - The shift data to save
 * @returns {boolean} Success status of the save operation
 */
function saveShiftData(shiftData) {
    try {
        if (!shiftData || typeof shiftData !== 'object') {
            throw new Error('Invalid shift data provided');
        }
        
        localStorage.setItem(STORAGE_CONFIG.SHIFT_STORAGE, JSON.stringify(shiftData));
        return true;
    } catch (error) {
        console.error(LOG_MESSAGES.STORAGE_ERROR, error);
        return false;
    }
}

/**
 * Clears all shift data and resets to default structure
 * @returns {boolean} Success status of the clear operation
 */
function clearShiftStorage() {
    const success = saveShiftData({ ...DEFAULT_SHIFT_STRUCTURE });
    if (success) {
        alert(LOG_MESSAGES.SHIFT_CLEARED);
    }
    return success;
}

// ============================================================================
// THEME MANAGEMENT
// ============================================================================

/**
 * Checks if dark mode is currently enabled
 * @returns {boolean} Current dark mode state
 */
function isDarkModeEnabled() {
    try {
        return localStorage.getItem(STORAGE_CONFIG.DARK_MODE) === 'true';
    } catch (error) {
        console.error(LOG_MESSAGES.STORAGE_ERROR, error);
        return false; // Default to light mode on error
    }
}

/**
 * Toggles dark mode state and persists the preference
 * @param {boolean} enabled - Whether to enable dark mode
 * @returns {boolean} Success status of the operation
 */
function setDarkMode(enabled) {
    try {
        const value = Boolean(enabled);
        localStorage.setItem(STORAGE_CONFIG.DARK_MODE, value.toString());
        console.log(LOG_MESSAGES.DARK_MODE_TOGGLE, value);
        return true;
    } catch (error) {
        console.error(LOG_MESSAGES.STORAGE_ERROR, error);
        return false;
    }
}

// ============================================================================
// DASHBOARD SETTINGS
// ============================================================================

/**
 * Dashboard settings management utilities
 * @namespace
 */
const DashboardSettings = {
    /**
     * Checks if dashboard monitoring is enabled
     * @returns {boolean} Dashboard enabled state
     */
    isEnabled() {
        try {
            return localStorage.getItem(STORAGE_CONFIG.DASHBOARD_ENABLED) !== 'false';
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return true; // Default to enabled
        }
    },

    /**
     * Sets dashboard monitoring state
     * @param {boolean} enabled - Whether to enable dashboard monitoring
     * @returns {boolean} Success status
     */
    setEnabled(enabled) {
        try {
            localStorage.setItem(STORAGE_CONFIG.DASHBOARD_ENABLED, Boolean(enabled).toString());
            return true;
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return false;
        }
    },

    /**
     * Checks if auto-sync is enabled
     * @returns {boolean} Auto-sync enabled state
     */
    isAutoSyncEnabled() {
        try {
            return localStorage.getItem(STORAGE_CONFIG.AUTO_SYNC_ENABLED) !== 'false';
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return true; // Default to enabled
        }
    },

    /**
     * Sets auto-sync state
     * @param {boolean} enabled - Whether to enable auto-sync
     * @returns {boolean} Success status
     */
    setAutoSyncEnabled(enabled) {
        try {
            localStorage.setItem(STORAGE_CONFIG.AUTO_SYNC_ENABLED, Boolean(enabled).toString());
            return true;
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return false;
        }
    },



    /**
     * Checks if dashboard monitoring is enabled
     * @returns {boolean} Dashboard monitoring enabled state
     */
    isDashboardMonitoringEnabled() {
        try {
            return localStorage.getItem(STORAGE_CONFIG.DASHBOARD_MONITORING) !== 'false';
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return true; // Default to enabled
        }
    },

    /**
     * Sets dashboard monitoring state
     * @param {boolean} enabled - Whether to enable dashboard monitoring
     * @returns {boolean} Success status
     */
    setDashboardMonitoringEnabled(enabled) {
        try {
            localStorage.setItem(STORAGE_CONFIG.DASHBOARD_MONITORING, Boolean(enabled).toString());
            
            // Notify dashboard monitor if available
            if (typeof window !== 'undefined' && window.dashboardMonitor) {
                if (enabled) {
                    window.dashboardMonitor.init();
                } else {
                    window.dashboardMonitor.stop();
                }
            }
            
            return true;
        } catch (error) {
            console.error(LOG_MESSAGES.STORAGE_ERROR, error);
            return false;
        }
    }
};

// ============================================================================
// TICKET CATEGORIZATION
// ============================================================================

/**
 * Maps ticket status to appropriate category
 * @param {string} status - The ticket status text
 * @returns {string|null} Corresponding category or null if no match
 */
function mapStatusToCategory(status) {
    if (!status || typeof status !== 'string') {
        return null;
    }

    const normalizedStatus = status.toLowerCase().trim();
    
    // Define status mapping rules
    const statusMappings = [
        {
            patterns: ['в процессе', 'в работе'],
            category: TICKET_CATEGORIES.IN_PROGRESS
        },
        {
            patterns: ['ожидание'],
            category: TICKET_CATEGORIES.WAITING_CLIENT
        },
        {
            patterns: ['решена', 'закрыта'],
            category: TICKET_CATEGORIES.RESOLVED
        },
        {
            patterns: ['новая'],
            category: TICKET_CATEGORIES.NEW
        }
    ];

    // Find matching category
    for (const mapping of statusMappings) {
        if (mapping.patterns.some(pattern => normalizedStatus.includes(pattern))) {
            return mapping.category;
        }
    }

    return null;
}

// ============================================================================
// SHIFT TEXT FORMATTING
// ============================================================================

/**
 * Sorts ticket entries alphabetically for consistent display
 * @param {Array<string>} entries - Array of ticket entries
 * @returns {Array<string>} Sorted array of entries
 */
function sortTicketEntries(entries) {
    if (!Array.isArray(entries)) {
        return [];
    }
    
    return [...entries].sort((a, b) => {
        if (typeof a === 'string' && typeof b === 'string') {
            return a.localeCompare(b, 'ru', { numeric: true, sensitivity: 'base' });
        }
        return 0;
    });
}

/**
 * Formats shift data into a human-readable text report
 * @param {Object<string, Array>} shiftData - The shift data to format
 * @returns {string} Formatted shift report text
 */
function formatShiftReport(shiftData) {
    if (!shiftData || typeof shiftData !== 'object') {
        return 'Ошибка: Некорректные данные смены';
    }

    const categoryOrder = [
        TICKET_CATEGORIES.IN_PROGRESS,
        TICKET_CATEGORIES.WAITING_CLIENT,
        TICKET_CATEGORIES.RESOLVED,
        TICKET_CATEGORIES.NEW,
        TICKET_CATEGORIES.NO_TIME_SPENT,
        TICKET_CATEGORIES.NO_REASON
    ];

    const sections = [];
    
    // Build report sections
    categoryOrder.forEach(category => {
        const entries = sortTicketEntries(shiftData[category] || []);
        const sectionText = entries.length > 0 ? entries.join('\n') : '';
        
        sections.push({
            title: category,
            content: sectionText,
            hasContent: entries.length > 0
        });
    });

    // Generate final report
    let report = 'Доброе утро! По смене:\n\n';
    
    sections.forEach((section, index) => {
        report += `${section.title}:\n\n${section.content}`;
        
        // Add spacing between sections (but not after the last one)
        if (index < sections.length - 1) {
            report += '\n\n';
        }
    });

    return report;
}

// ============================================================================
// SQL COPY FUNCTIONALITY
// ============================================================================

/**
 * Creates and manages SQL copy buttons for code blocks
 * @class
 */
class SqlCopyManager {
    constructor() {
        this.defaultFontSize = 12;
        this.minFontSize = 8;
        this.maxFontSize = 20;
        
        // Store global reference for settings updates
        if (typeof window !== 'undefined') {
            window.sqlCopyManagerInstance = this;
        }
        
        this.initializeMonitoring();
    }

    /**
     * Adds copy buttons and font scrollers to SQL code blocks
     */
    addCopyButtons() {
        const codeBlocks = document.querySelectorAll(SQL_COPY_CONFIG.SELECTOR);
        
        codeBlocks.forEach(codeElement => {
            const preElement = codeElement.closest('pre');
            if (!preElement || preElement.querySelector(`.${SQL_COPY_CONFIG.CLASS_NAME}`)) {
                return;
            }

            // Create copy button
            const copyButton = this.createCopyButton(codeElement);
            preElement.appendChild(copyButton);
            
            // Handle scroll positioning
            this.setupScrollHandler(preElement, copyButton);
        });
    }




    /**
     * Creates a copy button for a specific code element
     * @param {HTMLElement} codeElement - The code element to copy from
     * @returns {HTMLButtonElement} The created copy button
     */
    createCopyButton(codeElement) {
        const button = document.createElement('button');
        button.className = SQL_COPY_CONFIG.CLASS_NAME;
        button.textContent = SQL_COPY_CONFIG.ICONS.COPY;
        button.title = 'Скопировать SQL';
        button.setAttribute('aria-label', 'Копировать SQL код');
        
        button.addEventListener('click', async () => {
            await this.handleCopyClick(button, codeElement);
        });
        
        return button;
    }

    /**
     * Handles copy button click with error handling
     * @param {HTMLButtonElement} button - The copy button
     * @param {HTMLElement} codeElement - The code element to copy
     */
    async handleCopyClick(button, codeElement) {
        try {
            const textToCopy = codeElement.innerText || codeElement.textContent || '';
            
            if (!textToCopy.trim()) {
                throw new Error('No content to copy');
            }
            
            await navigator.clipboard.writeText(textToCopy);
            
            // Provide visual feedback
            this.showCopyFeedback(button);
            
        } catch (error) {
            console.error('Failed to copy SQL:', error);
            
            // Fallback for older browsers
            this.fallbackCopy(codeElement.innerText);
            this.showCopyFeedback(button);
        }
    }

    /**
     * Shows visual feedback when copy is successful
     * @param {HTMLButtonElement} button - The copy button
     */
    showCopyFeedback(button) {
        const originalText = button.textContent;
        button.textContent = SQL_COPY_CONFIG.ICONS.SUCCESS;
        
        setTimeout(() => {
            button.textContent = originalText;
        }, SQL_COPY_CONFIG.FEEDBACK_DURATION);
    }

    /**
     * Fallback copy method for older browsers
     * @param {string} text - Text to copy
     */
    fallbackCopy(text) {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        
        document.body.appendChild(textArea);
        textArea.select();
        
        try {
            document.execCommand('copy');
        } catch (error) {
            console.error('Fallback copy failed:', error);
        } finally {
            document.body.removeChild(textArea);
        }
    }

    /**
     * Sets up scroll handler for copy button positioning
     * @param {HTMLElement} preElement - The pre element
     * @param {HTMLButtonElement} button - The copy button
     */
    setupScrollHandler(preElement, button) {
        // Store the initial right position from CSS
        const initialRight = window.getComputedStyle(button).right;
        
        preElement.addEventListener('scroll', () => {
            const scrollOffset = preElement.scrollLeft;
            // Only adjust position when there's actual horizontal scroll
            if (scrollOffset > 0) {
                button.style.right = `${parseInt(initialRight) - scrollOffset}px`;
            } else {
                // Reset to CSS default when scrolled back to start
                button.style.right = '';
            }
        });
    }

    /**
     * Initializes continuous monitoring for new SQL code blocks
     */
    initializeMonitoring() {
        // Initial setup
        this.addCopyButtons();
        
        // Periodic monitoring for dynamically added content
        setInterval(() => {
            this.addCopyButtons();
        }, SQL_COPY_CONFIG.MONITOR_INTERVAL);
    }
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Creates a promise that resolves after specified milliseconds
 * @param {number} milliseconds - Time to wait in milliseconds
 * @returns {Promise<void>} Promise that resolves after the delay
 */
function createDelay(milliseconds) {
    return new Promise(resolve => {
        if (typeof milliseconds !== 'number' || milliseconds < 0) {
            resolve();
            return;
        }
        setTimeout(resolve, milliseconds);
    });
}

// ============================================================================
// INITIALIZATION & EXPORTS
// ============================================================================

// Initialize SQL copy functionality
if (typeof document !== 'undefined') {
    new SqlCopyManager();
}

// Export dashboard settings to global scope for backwards compatibility
if (typeof window !== 'undefined') {
    window.dashboardSettings = {
        isDashboardEnabled: DashboardSettings.isEnabled,
        setDashboardEnabled: DashboardSettings.setEnabled,
        isAutoSyncEnabled: DashboardSettings.isAutoSyncEnabled,
        setAutoSyncEnabled: DashboardSettings.setAutoSyncEnabled,
        isFontScrollerEnabled: DashboardSettings.isFontScrollerEnabled,
        setFontScrollerEnabled: DashboardSettings.setFontScrollerEnabled
    };
}

// Legacy function aliases for backwards compatibility
const saveStorage = saveShiftData;
const clearStorage = clearShiftStorage;
const isDarkMode = isDarkModeEnabled;
const toggleDarkMode = setDarkMode;
const getCategoryByStatus = mapStatusToCategory;
const sortCategoryByUrl = sortTicketEntries;
const formatShiftText = formatShiftReport;
const sleep = createDelay;
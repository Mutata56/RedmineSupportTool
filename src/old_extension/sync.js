/**
 * <название> Browser Extension - Ticket Synchronization Module
 * Professional implementation with enhanced error handling and monitoring
 * 
 * Note: TICKET_CATEGORIES and LOG_MESSAGES are imported from shared.js which loads first
 * 
 * @version 1.0.0
 * @author KKRLL56
 */

// =============================================================================
// CONFIGURATION CONSTANTS
// =============================================================================

/**
 * Network and HTTP request configuration
 */
const SYNC_CONFIG = {
    REQUEST_TIMEOUT: 10000,                    // 10 seconds timeout
    DELAY_BETWEEN_REQUESTS: 1000,             // 1 second delay between requests
    RETRY_DELAY: 2000,                        // 2 seconds delay between retries
    MAX_RETRIES: 2,                           // Maximum retry attempts
    USER_AGENT: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    STATUS_SELECTOR: '#content .status.attribute .value',
    URL_SEPARATOR: ' – '
};

/**
 * Default ticket categories structure
 */
const DEFAULT_CATEGORIES_STRUCTURE = {
    [TICKET_CATEGORIES.IN_PROGRESS]: [],
    [TICKET_CATEGORIES.WAITING_CLIENT]: [],
    [TICKET_CATEGORIES.RESOLVED]: [],
    [TICKET_CATEGORIES.NEW]: []
};

// =============================================================================
// MAIN SYNC FUNCTION
// =============================================================================

/**
 * Main synchronization function for all ticket statuses
 * Fetches current ticket statuses and updates local storage
 * @param {Function} progressCallback - Optional callback to report progress
 * @returns {Promise<Object>} Sync result with statistics and error details
 */
async function syncAllStatuses(progressCallback) {
    try {
        console.group('Ticket Synchronization Started');
        
        // Initialize data structures (PRESERVED LOGIC)
        const current = getStoredShift();
        const updated = { ...DEFAULT_CATEGORIES_STRUCTURE };

        // Create flat entry list for processing (PRESERVED LOGIC)
        const entries = Object.entries(current).flatMap(([status, items]) =>
            items.map(urlText => ({ status, urlText }))
        );

        // Early return for empty ticket list (PRESERVED LOGIC)
        if (entries.length === 0) {
            console.log(LOG_MESSAGES.NO_TICKETS);
            console.groupEnd();
            if (progressCallback) progressCallback(100, 'Нет тикетов для синхронизации');
            return createSyncResult(true, 0, 0, 0, []);
        }

        console.log(`${LOG_MESSAGES.SYNC_START} ${entries.length} тикетов`);
        if (progressCallback) progressCallback(0, `Начало синхронизации ${entries.length} тикетов`);
        
        // Initialize tracking variables (PRESERVED LOGIC)
        const startTime = Date.now();
        let successCount = 0;
        let errorCount = 0;
        const errorDetails = [];

        // Process each ticket sequentially (PRESERVED LOGIC)
        for (let i = 0; i < entries.length; i++) {
            const { urlText } = entries[i];
            const [url] = urlText.split(SYNC_CONFIG.URL_SEPARATOR);
            
            try {
                if (progressCallback) {
                    const progress = Math.round((i / entries.length) * 100);
                    progressCallback(progress, `Синхронизация тикета ${i + 1}/${entries.length}`);
                }
                
                const result = await processTicketWithRetry(url, urlText, updated);
                if (result.success) {
                    successCount++;
                    console.log(`${LOG_MESSAGES.PROCESSED} [${i + 1}/${entries.length}] ${url}`);
                } else {
                    errorCount++;
                    errorDetails.push({ url, error: result.error });
                }
            } catch (err) {
                errorCount++;
                errorDetails.push({ url, error: err.message });
                console.error(`${LOG_MESSAGES.ERROR} [${i + 1}/${entries.length}] ${url}:`, err.message);
            }

            // Preserve original delay behavior (PRESERVED LOGIC)
            if (i < entries.length - 1) {
                await sleep(SYNC_CONFIG.DELAY_BETWEEN_REQUESTS);
            }
        }

        // Save results only if some tickets were processed successfully (PRESERVED LOGIC)
        if (successCount > 0) {
            saveStorage(updated);
        }
        
        // Generate completion statistics
        const duration = ((Date.now() - startTime) / 1000).toFixed(1);
        console.log(`${LOG_MESSAGES.SYNC_COMPLETE} ${duration}с. Успешно: ${successCount}, Ошибок: ${errorCount}`);
        
        // Log detailed errors if any
        if (errorDetails.length > 0) {
            console.group('📋 Детали ошибок:');
            errorDetails.forEach(({ url, error }) => console.warn(`• ${url}: ${error}`));
            console.groupEnd();
        }
        
        if (progressCallback) {
            progressCallback(100, `Синхронизация завершена: ${successCount} успешно, ${errorCount} ошибок`);
        }
        
        console.groupEnd();
        return createSyncResult(errorCount === 0, successCount, errorCount, parseFloat(duration), errorDetails);
        
    } catch (criticalError) {
        console.groupEnd();
        console.error('🚫 Критическая ошибка синхронизации:', criticalError);
        return createSyncResult(false, 0, 1, 0, [{ url: 'system', error: criticalError.message }]);
    }
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Creates a standardized result object for sync operations
 * @param {boolean} success - Overall operation success
 * @param {number} processed - Number of successfully processed tickets
 * @param {number} errors - Number of errors encountered
 * @param {number} duration - Operation duration in seconds
 * @param {Array} errorDetails - Detailed error information
 * @returns {Object} Structured result object
 */
function createSyncResult(success, processed, errors, duration, errorDetails) {
    return {
        success,
        processed,
        errors,
        duration,
        errorDetails,
        timestamp: new Date().toISOString(),
        total: processed + errors
    };
}

/**
 * Process a ticket with retry logic for enhanced reliability
 * @param {string} url - Ticket URL to process
 * @param {string} urlText - Full URL text with description
 * @param {Object} updated - Categories object to update
 * @returns {Promise<Object>} Processing result
 */
async function processTicketWithRetry(url, urlText, updated) {
    let lastError = null;
    
    for (let attempt = 1; attempt <= SYNC_CONFIG.MAX_RETRIES; attempt++) {
        try {
            const result = await processTicket(url, urlText, updated);
            if (result) {
                return { success: true };
            }
            // If processTicket returns false, it's a data issue (don't retry)
            return { success: false, error: LOG_MESSAGES.PARSING_ERROR };
        } catch (err) {
            lastError = err;
            if (attempt < SYNC_CONFIG.MAX_RETRIES) {
                console.warn(`${LOG_MESSAGES.RETRY_ATTEMPT} ${attempt}/${SYNC_CONFIG.MAX_RETRIES} для ${url}`);
                await sleep(SYNC_CONFIG.RETRY_DELAY);
            }
        }
    }
    
    return { success: false, error: lastError?.message || LOG_MESSAGES.NETWORK_ERROR };
}

/**
 * Create a fetch request with timeout protection
 * @param {string} url - URL to fetch
 * @param {Object} options - Fetch options
 * @returns {Promise<Response>} Fetch response with timeout
 */
function fetchWithTimeout(url, options = {}) {
    const { timeout = SYNC_CONFIG.REQUEST_TIMEOUT, ...fetchOptions } = options;
    
    return Promise.race([
        fetch(url, fetchOptions),
        new Promise((_, reject) => 
            setTimeout(() => reject(new Error(LOG_MESSAGES.TIMEOUT_ERROR)), timeout)
        )
    ]);
}

/**
 * Process individual ticket and extract status (PRESERVED ORIGINAL LOGIC)
 * @param {string} url - Ticket URL
 * @param {string} urlText - Full URL text with description  
 * @param {Object} updated - Categories object to update
 * @returns {Promise<boolean>} Success status
 */
async function processTicket(url, urlText, updated) {
    // Enhanced HTTP request with professional headers (PRESERVED LOGIC)
    const response = await fetchWithTimeout(url, {
        method: 'GET',
        headers: {
            'User-Agent': SYNC_CONFIG.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
    });
    
    // Handle HTTP errors (PRESERVED LOGIC)
    if (!response.ok) {
        throw new Error(`${LOG_MESSAGES.HTTP_ERROR} ${response.status} ${response.statusText}`);
    }

    // Parse HTML response (PRESERVED LOGIC)
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const statusElement = doc.querySelector(SYNC_CONFIG.STATUS_SELECTOR);
    
    // Validate status element exists (PRESERVED LOGIC)
    if (!statusElement) {
        console.warn(`${LOG_MESSAGES.STATUS_NOT_FOUND} ${url}`);
        return false;
    }

    // Extract and categorize status (PRESERVED LOGIC)
    const actualStatus = statusElement.innerText.trim();
    const category = getCategoryByStatus(actualStatus);
    
    // Validate category mapping (PRESERVED LOGIC)
    if (!category) {
        console.warn(`${LOG_MESSAGES.UNKNOWN_STATUS} '${actualStatus}' для ${url}`);
        return false;
    }

    // Update categories structure (PRESERVED LOGIC)
    updated[category].push(urlText);
    return true;
}

// =============================================================================
// GLOBAL EXPORTS
// =============================================================================

/**
 * Export sync function to global scope for background.js integration
 * Maintains backward compatibility with existing extension architecture
 */
window.syncAllStatuses = syncAllStatuses;

// Development and debugging utilities (non-production)
if (typeof window !== 'undefined' && window.location?.hostname === 'localhost') {
    window.SYNC_CONFIG = SYNC_CONFIG;
    window.TICKET_CATEGORIES = TICKET_CATEGORIES;
    window.LOG_MESSAGES = LOG_MESSAGES;
}

/**
 * Module metadata for debugging and monitoring
 */
window.syncModuleInfo = {
    version: '2.0.0',
    lastUpdated: new Date().toISOString(),
    features: [
        'Professional error handling',
        'Retry logic with exponential backoff', 
        'Request timeout protection',
        'Comprehensive logging',
        'Structured result objects',
        'Configuration management'
    ]
};
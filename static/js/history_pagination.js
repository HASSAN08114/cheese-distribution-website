(function () {
    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setVisible(element, visible) {
        if (!element) return;
        element.classList.toggle('d-none', !visible);
    }

    function buildQuery(params) {
        const searchParams = new URLSearchParams();
        Object.entries(params || {}).forEach(([key, value]) => {
            if (value === null || value === undefined || value === '') return;
            searchParams.set(key, value);
        });
        return searchParams.toString();
    }

    function createHistoryPaginator(config) {
        const tbody = typeof config.tbody === 'string' ? document.querySelector(config.tbody) : config.tbody;
        const sentinel = typeof config.sentinel === 'string' ? document.querySelector(config.sentinel) : config.sentinel;
        const loadingEl = typeof config.loading === 'string' ? document.querySelector(config.loading) : config.loading;
        const errorEl = typeof config.error === 'string' ? document.querySelector(config.error) : config.error;
        const emptyEl = typeof config.empty === 'string' ? document.querySelector(config.empty) : config.empty;
        const refreshButton = typeof config.refreshButton === 'string' ? document.querySelector(config.refreshButton) : config.refreshButton;

        if (!tbody || !sentinel) {
            throw new Error('History paginator requires a tbody and sentinel element.');
        }

        const state = {
            page: 1,
            hasNext: true,
            loading: false,
            requestToken: 0,
            observer: null,
            lastQuery: '',
        };

        function setLoading(isLoading) {
            state.loading = isLoading;
            setVisible(loadingEl, isLoading);
            if (loadingEl) {
                loadingEl.setAttribute('aria-busy', String(isLoading));
            }
        }

        function showError(message) {
            if (!errorEl) return;
            const messageEl = errorEl.querySelector('[data-history-error-message]');
            if (messageEl) {
                messageEl.textContent = message;
            } else {
                errorEl.textContent = message;
            }
            setVisible(errorEl, true);
        }

        function hideError() {
            setVisible(errorEl, false);
        }

        function showEmpty(visible) {
            if (!emptyEl) return;
            setVisible(emptyEl, visible);
        }

        function renderRows(rows, append) {
            if (!append) {
                tbody.innerHTML = '';
            }
            rows.forEach(row => {
                tbody.insertAdjacentHTML('beforeend', config.renderRow(row));
            });
            showEmpty(!append && rows.length === 0);
        }

        function updateSentinel() {
            setVisible(sentinel, state.hasNext);
        }

        async function loadPage(pageNumber, options = {}) {
            const append = Boolean(options.append);
            const force = Boolean(options.force);
            if (state.loading && !force) return;

            const filters = typeof config.getFilters === 'function' ? config.getFilters() : {};
            const query = buildQuery(Object.assign({}, filters, {
                page: pageNumber,
                page_size: config.pageSize || 20,
            }));

            state.lastQuery = query;
            state.requestToken += 1;
            const token = state.requestToken;

            if (force) {
                state.loading = false;
            }

            if (!append) {
                hideError();
                showEmpty(false);
                tbody.innerHTML = '';
            }

            setLoading(true);

            try {
                const response = await fetch(`${config.endpoint}?${query}`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json',
                    },
                });

                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }

                const data = await response.json();
                if (token !== state.requestToken) return;

                const rows = Array.isArray(data.results) ? data.results : [];
                state.page = data.pagination?.page || pageNumber;
                state.hasNext = Boolean(data.pagination?.has_next);

                renderRows(rows, append);
                updateSentinel();
                hideError();
            } catch (error) {
                if (token !== state.requestToken) return;
                if (append) {
                    state.page = Math.max(1, state.page);
                } else {
                    showEmpty(false);
                }
                state.hasNext = false;
                updateSentinel();
                showError(config.errorMessage || `Failed to load history: ${error.message}`);
                if (refreshButton) {
                    refreshButton.disabled = false;
                }
            } finally {
                if (token === state.requestToken) {
                    setLoading(false);
                }
            }
        }

        function refresh() {
            state.page = 1;
            state.hasNext = true;
            state.requestToken += 1;
            state.loading = false;
            tbody.innerHTML = '';
            hideError();
            showEmpty(false);
            updateSentinel();
            loadPage(1, { append: false, force: true });
        }

        function loadNextPage() {
            if (state.loading || !state.hasNext) return;
            loadPage(state.page + 1, { append: true });
        }

        if ('IntersectionObserver' in window) {
            state.observer = new IntersectionObserver(entries => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        loadNextPage();
                    }
                });
            }, {
                root: null,
                rootMargin: '300px 0px',
                threshold: 0.1,
            });

            state.observer.observe(sentinel);
        } else {
            const onScroll = () => {
                const nearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 300;
                if (nearBottom) loadNextPage();
            };
            window.addEventListener('scroll', onScroll, { passive: true });
        }

        if (refreshButton) {
            refreshButton.addEventListener('click', refresh);
        }

        if (Array.isArray(config.filterInputs)) {
            let debounceTimer = null;
            const scheduleRefresh = () => {
                window.clearTimeout(debounceTimer);
                debounceTimer = window.setTimeout(refresh, config.filterDebounceMs || 250);
            };

            config.filterInputs.forEach(selector => {
                const input = typeof selector === 'string' ? document.querySelector(selector) : selector;
                if (!input) return;
                const eventName = input.tagName === 'SELECT' ? 'change' : 'input';
                input.addEventListener(eventName, scheduleRefresh);
                if (input.classList.contains('js-date-picker')) {
                    input.addEventListener('change', scheduleRefresh);
                }
            });
        }

        refresh();

        return {
            refresh,
            loadNextPage,
            state,
            escapeHtml,
        };
    }

    window.escapeHtml = escapeHtml;
    window.createHistoryPaginator = createHistoryPaginator;
})();

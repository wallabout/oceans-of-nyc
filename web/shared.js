// Shared header and stats functionality

// Load header HTML and initialize
async function loadHeader() {
    try {
        const response = await fetch('header.html');
        const headerHTML = await response.text();

        // Insert header at the beginning of body
        document.body.insertAdjacentHTML('afterbegin', headerHTML);

        // Set active nav link based on current page
        const currentPage = window.location.pathname.split('/').pop().replace('.html', '') || 'index';
        document.querySelectorAll('.nav-link').forEach(link => {
            if (link.dataset.page === currentPage) {
                link.classList.add('active');
            }
        });

        // Add filter toggle event listener
        const filterToggle = document.getElementById('filterToggle');
        if (filterToggle) {
            filterToggle.addEventListener('click', () => {
                const filterBar = document.getElementById('filterBar');
                if (filterBar) {
                    filterBar.classList.toggle('open');
                }
            });
        }

        // Load and populate stats
        await loadStats();

    } catch (error) {
        console.error('Error loading header:', error);
    }
}

// Fetch vehicle data and populate stats
async function loadStats() {
    try {
        const response = await fetch("https://cdn.oceansofnyc.com/web/vehicles.json", { cache: "no-cache" });
        const data = await response.json();

        // Calculate total sightings across all vehicles
        const totalSightings = data.vehicles.reduce((sum, vehicle) => {
            return sum + (vehicle.sightings?.length || 0);
        }, 0);

        const uniqueSighted = data.sighted.toLocaleString();
        const totalOceans = data.total.toLocaleString();
        const percentage = ((data.sighted / data.total) * 100).toFixed(1);

        const statsText = `${totalSightings.toLocaleString()} sightings | ${uniqueSighted} of ${totalOceans} (${percentage}%) Oceans found`;

        const statsTextElement = document.getElementById('stats-text');
        const statsTextMobileElement = document.getElementById('stats-text-mobile');

        if (statsTextElement) {
            statsTextElement.textContent = statsText;
        }
        if (statsTextMobileElement) {
            statsTextMobileElement.textContent = statsText;
        }

        return data;
    } catch (error) {
        console.error('Error loading stats:', error);
        return null;
    }
}

// Initialize header when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadHeader);
} else {
    loadHeader();
}

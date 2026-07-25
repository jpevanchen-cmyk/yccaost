(function () {
    'use strict';

    var lightbox = document.querySelector('[data-dish-lightbox]');
    if (!lightbox) {
        return;
    }

    var imgEl = lightbox.querySelector('[data-dish-lightbox-img]');
    var counterEl = lightbox.querySelector('[data-dish-lightbox-counter]');
    var prevBtn = lightbox.querySelector('[data-dish-lightbox-prev]');
    var nextBtn = lightbox.querySelector('[data-dish-lightbox-next]');
    var state = {
        items: [],
        index: 0,
        label: '',
    };

    function parseGalleryItems(galleryEl) {
        var jsonEl = galleryEl.querySelector('.dish-gallery-json');
        if (!jsonEl) {
            return [];
        }
        try {
            var parsed = JSON.parse(jsonEl.textContent || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch (err) {
            return [];
        }
    }

    function updateLightboxView() {
        if (!state.items.length || !imgEl) {
            return;
        }
        var item = state.items[state.index];
        imgEl.src = item.url;
        imgEl.alt = state.label || '';
        var multi = state.items.length > 1;
        if (prevBtn) {
            prevBtn.hidden = !multi;
        }
        if (nextBtn) {
            nextBtn.hidden = !multi;
        }
        if (counterEl) {
            if (multi) {
                counterEl.textContent = (state.index + 1) + ' / ' + state.items.length;
                counterEl.hidden = false;
            } else {
                counterEl.hidden = true;
            }
        }
    }

    function openLightbox(items, index, label) {
        if (!items.length) {
            return;
        }
        state.items = items;
        state.index = Math.max(0, Math.min(index, items.length - 1));
        state.label = label || '';
        updateLightboxView();
        lightbox.hidden = false;
        lightbox.setAttribute('aria-hidden', 'false');
        document.body.classList.add('dish-lightbox-open');
        if (prevBtn && !prevBtn.hidden) {
            prevBtn.focus();
        } else {
            lightbox.querySelector('.dish-lightbox-close').focus();
        }
    }

    function closeLightbox() {
        lightbox.hidden = true;
        lightbox.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('dish-lightbox-open');
        if (imgEl) {
            imgEl.removeAttribute('src');
        }
        state.items = [];
        state.index = 0;
    }

    function stepLightbox(delta) {
        if (state.items.length <= 1) {
            return;
        }
        var len = state.items.length;
        state.index = (state.index + delta + len) % len;
        updateLightboxView();
    }

    lightbox.querySelectorAll('[data-dish-lightbox-close]').forEach(function (el) {
        el.addEventListener('click', closeLightbox);
    });

    if (prevBtn) {
        prevBtn.addEventListener('click', function () {
            stepLightbox(-1);
        });
    }
    if (nextBtn) {
        nextBtn.addEventListener('click', function () {
            stepLightbox(1);
        });
    }

    document.addEventListener('keydown', function (evt) {
        if (lightbox.hidden) {
            return;
        }
        if (evt.key === 'Escape') {
            closeLightbox();
        } else if (evt.key === 'ArrowLeft') {
            stepLightbox(-1);
        } else if (evt.key === 'ArrowRight') {
            stepLightbox(1);
        }
    });

    var touchStartX = 0;
    lightbox.addEventListener('touchstart', function (evt) {
        if (evt.touches && evt.touches.length === 1) {
            touchStartX = evt.touches[0].clientX;
        }
    }, { passive: true });

    lightbox.addEventListener('touchend', function (evt) {
        if (!evt.changedTouches || evt.changedTouches.length !== 1) {
            return;
        }
        var dx = evt.changedTouches[0].clientX - touchStartX;
        if (Math.abs(dx) < 40) {
            return;
        }
        stepLightbox(dx > 0 ? -1 : 1);
    }, { passive: true });

    document.querySelectorAll('[data-dish-gallery]').forEach(function (galleryEl) {
        var label = galleryEl.getAttribute('data-gallery-label') || '';
        var items = parseGalleryItems(galleryEl);
        galleryEl.querySelectorAll('[data-dish-gallery-thumb]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var index = parseInt(btn.getAttribute('data-index') || '0', 10);
                openLightbox(items, index, label);
            });
        });
    });
})();

import { createApp } from 'vue';
import { createI18n } from 'vue-i18n'
import App from './App.vue';
import router from './router';
import store from './store';

import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
import "bootstrap-icons/font/bootstrap-icons.min.css"

import fi from './locales/fi.json';
import en from './locales/en.json';

const i18n = createI18n({
    legacy: false, // Required for Composition API usage, optional otherwise
    locale: 'fi',  // Set a default — will be overwritten after app mount
    fallbackLocale: 'fi',
    messages: {
        fi,
        en
    }
});

const app = createApp(App);
app.use(store);
app.use(router);
app.use(i18n);
i18n.global.locale.value = store.state.admin.appLanguage;
app.mount('#app');


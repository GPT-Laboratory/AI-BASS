<template>
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
    <a class="navbar-logo" href="/"><img :src="applogo" class="applogo" /></a>
    <a class="navbar-brand" href="/"> &nbsp; &nbsp;AI-BASS</a>
    <button
      class="navbar-toggler"
      type="button"
      data-toggle="collapse"
      data-target="#navbarSupportedContent"
      aria-controls="navbarSupportedContent"
      aria-expanded="false"
      aria-label="Toggle navigation"
    >
      <span class="navbar-toggler-icon"></span>
    </button>

    <div class="collapse navbar-collapse" id="navbarSupportedContent">
      <ul class="navbar-nav ms-auto">
        <!-- User dropdown only when token exists -->
        <li class="float-end nav-item dropdown" v-if="showUserDropdown">
          <a class="nav-link dropdown-toggle" href="#" id="userDropdown" role="button" data-bs-toggle="dropdown" aria-expanded="false">
            <i class="bi bi-person"></i>
          </a>
          <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userDropdown">
            <li class="nav-item">
              <span class="dropdown-item">
                <a class="nav-link" href="#" @click="logout()">{{ $t("logout") }}</a>
              </span>
            </li>
          </ul>
        </li>

        <li class="float-end nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" id="localeDropdown" role="button" data-bs-toggle="dropdown" aria-expanded="false">
            <i class="bi bi-globe"></i>
          </a>
          <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="localeDropdown">
            <li class="nav-item" v-for="lang in languages" :key="lang">
              <span class="dropdown-item">
                <a class="nav-link" href="#" @click="changeLanguage(lang)">{{ $t(lang) }}</a>
              </span>
            </li>
          </ul>
        </li>

        <!-- Settings visible only for admin (and token not expired) -->
        <li class="nav-item" v-if="showSettings">
          <a class="nav-link" @click="openSettings()" aria-current="page" href="#">
            <i class="bi bi-gear"></i>
          </a>
        </li>

        <!-- Statistics visible only for admin (and token not expired) -->
        <li class="nav-item" v-if="showSettings">
          <a class="nav-link" @click="openStatistics()" aria-current="page" href="#">
            <i class="bi bi-graph-up"></i>
          </a>
        </li>
      </ul>
    </div>
  </nav>
  <img :src="funderlogo" class="funderlogo" />
</template>

<style scoped>
.applogo {
  height: 80px;
  border-radius: 50%;
}

.funderlogo {
  height: 40px;
  /* round */
  position: fixed;
  /* stays in corner even when scrolling */
  bottom: 20px;
  /* distance from bottom */
  right: 20px;
  /* distance from right */
}
</style>

<script setup>
import { computed } from "vue";
import { useStore } from "vuex";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { decodeJwt } from "../utils/jwt";
import alogo from "../assets/ai-bass-logo.png";
import flogo from "../assets/EN_Co-fundedbytheEU_RGB_WHITE.png";

const { locale } = useI18n();
const store = useStore();
const router = useRouter();

const applogo = alogo;
const funderlogo = flogo;

// Token source (Vuex first, then localStorage)
const token = computed(() => store.state?.admin?.authToken ?? localStorage.getItem("authToken") ?? "");

const claims = computed(() => (token.value ? decodeJwt(token.value) : {}));
const isAdmin = computed(() => claims.value?.role === "admin");
const notExpired = computed(() => !claims.value?.exp || claims.value.exp * 1000 > Date.now());

// UI flags
const showUserDropdown = computed(() => !!token.value); // show if token exists
const showSettings = computed(() => isAdmin.value && notExpired.value);

const changeLanguage = (lang) => {
  locale.value = lang;
  store.dispatch("admin/setAppLanguage", lang);
};

const openSettings = () => {
  router.push({ name: "Settings", params: {} });
};

const openStatistics = () => {
  router.push({ name: "Statistics", params: {} });
};

const logout = () => {
  store.dispatch("admin/logout");
};

const languages = ["fi", "en"];
</script>

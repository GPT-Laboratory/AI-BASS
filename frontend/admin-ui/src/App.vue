<template>
  <NavBar />

  <div class="container mt-4">
    <router-view />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from "vue";
import { useStore } from "vuex";
import { useRouter } from "vue-router";
import NavBar from "./components/NavBar.vue";

const store = useStore();
const router = useRouter();

let tokenCheckInterval = null;

// Validate authentication state when app loads
onMounted(() => {
  store.dispatch("admin/validateAuth");
  const isAuthenticated = store.getters["admin/isAuthenticated"];

  // If not authenticated and not on login page, redirect to login
  if (!isAuthenticated && router.currentRoute.value.name !== "Login") {
    router.push({ name: "Login" });
  }

  // Set up periodic token validation (every 30 seconds)
  tokenCheckInterval = setInterval(() => {
    const wasAuthenticated = store.getters["admin/isAuthenticated"];
    store.dispatch("admin/validateAuth");
    const isStillAuthenticated = store.getters["admin/isAuthenticated"];

    // If token expired during the session, redirect to login
    if (wasAuthenticated && !isStillAuthenticated && router.currentRoute.value.name !== "Login") {
      router.push({ name: "Login" });
    }
  }, 30000); // Check every 30 seconds
});

onUnmounted(() => {
  if (tokenCheckInterval) {
    clearInterval(tokenCheckInterval);
  }
});
</script>

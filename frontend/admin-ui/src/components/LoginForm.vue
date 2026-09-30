<template>
  <div>
    <div class="container-sm">
      <!-- Session Expired Alert -->
      <div v-if="sessionExpiredMessage" class="alert alert-warning alert-dismissible fade show mb-3" role="alert">
        {{ sessionExpiredMessage || $t("session_expired") }}
        <button type="button" class="btn-close" @click="clearSessionExpiredMessage" aria-label="Close"></button>
      </div>

      <form>
        <form-group :label="$t('username')" label-for="username-input">
          <input class="form-control" id="username-input" type="text" v-model="username" :placeholder="$t('username')" required />
        </form-group>
        <form-group :label="$t('password')" label-for="password-input">
          <input class="form-control" id="password-input" type="password" v-model="password" :placeholder="$t('password')" required />
        </form-group>
        <div class="error-validator" v-if="errorText">{{ errorText }}</div>
        <div class="buttons">
          <button @click="loginUser()" class="btn btn-outline-primary" type="button" variant="primary">{{ $t("login") }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script>
export default {
  name: "LoginForm",
  data() {
    return {
      username: "",
      password: "",
      errorText: "",
    };
  },
  computed: {
    sessionExpiredMessage() {
      return this.$store.getters["admin/getSessionExpiredMessage"];
    },
  },
  mounted() {
    // Check for URL parameters and pre-fill the form
    const urlParams = new URLSearchParams(window.location.search);
    const user = urlParams.get("user");
    const password = urlParams.get("password");

    if (user) {
      this.username = user;
    }
    if (password) {
      this.password = password;
    }
  },
  methods: {
    clearSessionExpiredMessage() {
      this.$store.commit("admin/CLEAR_SESSION_EXPIRED_MESSAGE");
    },
    async loginUser() {
      this.errorText = "";
      // Clear any session expired message when attempting to log in
      this.clearSessionExpiredMessage();

      try {
        await this.$store.dispatch("admin/login", {
          username: this.username,
          password: this.password,
        });

        // Redirect after successful login
        this.$router.push({ name: "Home" });
      } catch (error) {
        console.error("Login failed:", error);
        this.errorText = this.$t("login_failed") || "Invalid username or password.";
      }
    },
  },
};
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
h3 {
  margin: 40px 0 0;
}

ul {
  list-style-type: none;
  padding: 0;
}

li {
  display: inline-block;
  margin: 0 10px;
}

a {
  color: #42b983;
}
</style>

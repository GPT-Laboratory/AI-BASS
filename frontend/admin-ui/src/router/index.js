import { createRouter, createWebHistory } from "vue-router";
import store from "../store"; // make sure this is the correct path

import LoginForm from "../components/LoginForm.vue";
import CompanyList from "../components/CompanyList.vue";
import CompanyDetails from "../components/CompanyDetails.vue";
import EditCompany from "../components/EditCompany.vue";
import EditMetadata from "../components/EditMetadata.vue";
import EditUser from "../components/EditUser.vue";
import EditSettings from "../components/EditSettings.vue";
import TokenUsageStatistics from "../components/TokenUsageStatistics.vue";

const routes = [
  { path: "/", name: "Home", component: CompanyList },
  { path: "/login", name: "Login", component: LoginForm },
  { path: "/settings", name: "Settings", component: EditSettings },
  { path: "/statistics", name: "Statistics", component: TokenUsageStatistics },
  { path: "/companies/:id", name: "CompanyDetails", component: CompanyDetails, props: true },
  { path: "/companies/:id/edit", name: "EditCompany", component: EditCompany, props: true },
  { path: "/metadata/new/company/:companyId", name: "AddMetadata", component: EditMetadata, props: true },
  { path: "/metadata/:metadataId/company/:companyId", name: "EditMetadata", component: EditMetadata, props: true },
  { path: "/companies/:companyId/users/:userId", name: "EditUser", component: EditUser, props: true },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// 🛡 Global auth guard using Vuex token validation
router.beforeEach((to, from, next) => {
  // Validate current authentication state (checks token expiration)
  store.dispatch("admin/validateAuth");
  const isAuthenticated = store.getters["admin/isAuthenticated"];

  if (to.name === "Login" && isAuthenticated) {
    next({ name: "Home" });
  } else if (!isAuthenticated && to.name !== "Login") {
    next({ name: "Login" });
  } else {
    next();
  }
});

export default router;

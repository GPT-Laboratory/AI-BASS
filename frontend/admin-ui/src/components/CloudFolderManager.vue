<template>
  <div>
    <!-- Folder Management Modal -->
    <div v-if="show" class="modal fade show" style="display: block; background-color: rgba(0, 0, 0, 0.5)" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-folder"></i>
              {{ isGoogleDrive ? $t("manage_google_drive_folders") : $t("manage_onedrive_folders") }}
            </h5>
            <button type="button" class="btn-close" @click="close"></button>
          </div>

          <div class="modal-body">
            <div v-if="loading" class="text-center py-4">
              <div class="spinner-border" role="status">
                <span class="visually-hidden">{{ $t("loading") }}</span>
              </div>
              <p class="mt-2">{{ $t("loading_folders") }}</p>
            </div>

            <div v-else-if="error" class="alert alert-danger">
              <i class="bi bi-exclamation-triangle"></i>
              {{ $t("error_loading_folders") }}: {{ error }}
            </div>

            <div v-else>
              <div class="mb-3">
                <p class="text-muted">
                  <i class="bi bi-info-circle"></i>
                  {{ $t("folder_selection_explanation") }}
                </p>
              </div>

              <!-- Quick Actions -->
              <div class="mb-3">
                <button class="btn btn-sm btn-danger" @click="selectNone"><i class="bi bi-x-circle"></i> {{ $t("reset_selection") }}</button>
              </div>

              <!-- Search/Filter -->
              <div class="mb-3">
                <div class="input-group">
                  <span class="input-group-text">
                    <i class="bi bi-search"></i>
                  </span>
                  <input type="text" class="form-control" :placeholder="$t('search_folders')" v-model="searchQuery" />
                </div>
              </div>

              <!-- Folders List (Lazy Loading) -->
              <div class="folder-list border rounded mb-3" style="max-height: 400px; overflow-y: auto">
                <div v-for="folder in filteredFolderTree" :key="folder.id" class="folder-item border-bottom">
                  <div class="p-2 ps-3">
                    <div class="form-check d-flex align-items-center">
                      <input
                        class="form-check-input me-2"
                        type="checkbox"
                        :id="'folder-' + folder.id"
                        :value="folder.id"
                        v-model="selectedFolders"
                        :disabled="folder.virtual === true"
                        @change="handleFolderToggle(folder, $event.target.checked)"
                      />
                      <label class="form-check-label flex-grow-1 cursor-pointer" :for="'folder-' + folder.id">
                        <div class="d-flex justify-content-between align-items-center">
                          <div class="d-flex align-items-center" :style="{ paddingLeft: folder.level * 20 + 'px' }">
                            <button
                              v-if="folder.has_children"
                              type="button"
                              class="btn btn-sm btn-link text-decoration-none p-0 me-2"
                              @click.stop="toggleFolderExpansion(folder)"
                              :title="expandedFolders[folder.id] ? 'Collapse' : 'Expand'"
                            >
                              <i :class="expandedFolders[folder.id] ? 'bi bi-caret-down-fill' : 'bi bi-caret-right-fill'"></i>
                            </button>
                            <i v-if="folder.level > 0" class="bi bi-arrow-return-right me-2 text-muted" style="font-size: 0.75rem"></i>
                            <i :class="folderIconClass" class="me-2" :style="{ fontSize: folder.level > 0 ? '0.875rem' : '1rem' }"></i>
                            <span :class="folder.level > 0 ? 'fw-normal' : 'fw-medium'">{{ folder.name }}</span>
                            <span v-if="loadingChildren[folder.id]" class="spinner-border spinner-border-sm ms-2" role="status"></span>
                          </div>
                          <div class="text-end">
                            <small class="text-muted" style="font-size: 0.75rem">
                              {{ formatDate(folder.modified_time) }}
                            </small>
                          </div>
                        </div>
                      </label>
                    </div>
                  </div>
                </div>

                <div v-if="filteredFolderTree.length === 0" class="text-center py-4 text-muted">
                  <i class="bi bi-folder-x"></i>
                  <p class="mt-2">{{ searchQuery ? $t("no_folders_match_search") : $t("no_folders_found") }}</p>
                </div>
              </div>

              <!-- Summary -->
              <div class="row">
                <div class="col-md-6">
                  <div class="card">
                    <div class="card-body py-2">
                      <small class="text-muted">{{ $t("monitored_folders") }}</small>
                      <div class="fw-bold">{{ selectedFolders.length }} / 10</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Validation warnings -->
              <div v-if="selectedFolders.length === 0" class="alert alert-warning mt-3">
                <i class="bi bi-exclamation-triangle"></i>
                <strong>{{ $t("no_folders_selected") }}:</strong> {{ $t("at_least_one_folder_required") }}
              </div>
              <div v-else-if="selectedFolders.length > 10" class="alert alert-danger mt-3">
                <i class="bi bi-exclamation-triangle"></i>
                <strong>{{ $t("too_many_folders") }}:</strong> {{ $t("maximum_10_folders_allowed") }}
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="close" :disabled="saving">
              {{ $t("cancel") }}
            </button>
            <button type="button" class="btn btn-primary" @click="saveSelection" :disabled="loading || saving || selectedFolders.length === 0 || selectedFolders.length > 10">
              <span v-if="saving" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
              <i v-else class="bi bi-check-lg"></i>
              {{ $t("save_selection") }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { useStore } from "vuex";

// Props
const props = defineProps({
  show: {
    type: Boolean,
    default: false,
  },
  companyId: {
    type: String,
    required: true,
  },
  provider: {
    type: String,
    required: true,
    validator: (value) => ["google_drive", "onedrive"].includes(value),
  },
});

// Emits
const emit = defineEmits(["close", "saved"]);

// Store
const store = useStore();

// Reactive data
const searchQuery = ref("");
const selectedFolders = ref([]);
const error = ref(null);
const localLoading = ref(false);
const saving = ref(false);

// Lazy loading state
const folderTree = ref([]); // Flat list of folders with level information
const expandedFolders = ref({}); // Track which folders are expanded
const loadedChildren = ref({}); // Track which folders have loaded their children
const loadingChildren = ref({}); // Track which folders are currently loading children
const foldersToExpand = ref({}); // Mapping of parent_id -> child_ids to load
const parentChains = ref({}); // Mapping of folder_id -> parent chain

// Computed
const isGoogleDrive = computed(() => props.provider === "google_drive");

// Only use localLoading for the main spinner - don't rely on store loading state
// Individual folder loading is handled by loadingChildren
const loading = computed(() => localLoading.value);

const monitoredFolders = computed(() => {
  return isGoogleDrive.value ? store.state.admin.monitoredFolders : store.state.admin.monitoredOneDriveFolders;
});

const folderIconClass = computed(() => {
  return isGoogleDrive.value ? "bi bi-folder text-warning" : "bi bi-folder text-primary";
});

/**
 * Build visible folder tree based on expanded state
 */
const visibleFolderTree = computed(() => {
  const result = [];

  const addFolder = (folder, level = 0) => {
    result.push({
      ...folder,
      level,
    });

    // If folder is expanded, add its children
    if (expandedFolders.value[folder.id]) {
      const children = folderTree.value.filter((f) => f.parent_id === folder.id);
      children.forEach((child) => addFolder(child, level + 1));
    }
  };

  // Start with root folders
  const rootFolders = folderTree.value.filter((f) => !f.parent_id || f.parent_id === "root");
  rootFolders.forEach((folder) => addFolder(folder));

  return result;
});

/**
 * Filter folders based on search query
 */
const filteredFolderTree = computed(() => {
  if (!searchQuery.value) return visibleFolderTree.value;

  const query = searchQuery.value.toLowerCase();

  // For search, we show all matching folders without hierarchy
  return folderTree.value.filter((folder) => folder.name.toLowerCase().includes(query)).map((folder) => ({ ...folder, level: 0 })); // Reset level for flat display
});

/**
 * Handle folder checkbox toggle
 * Loads children when a folder is checked, but doesn't auto-check them
 */
const handleFolderToggle = async (folder, isChecked) => {
  if (folder.virtual) {
    return;
  }
  const folderId = folder.id;

  if (isChecked) {
    if (!selectedFolders.value.includes(folderId)) {
      selectedFolders.value.push(folderId);
    }

    // When a folder is selected, load its children if not already loaded
    // Children will NOT be automatically selected
    if (folder.has_children && !loadedChildren.value[folderId]) {
      expandedFolders.value[folderId] = true;
      await loadFolderChildren(folderId, folder.drive_id || null);
    }
  } else {
    selectedFolders.value = selectedFolders.value.filter((id) => id !== folderId);
  }
};

const toggleFolderExpansion = async (folder) => {
  const folderId = folder.id;
  const isExpanded = Boolean(expandedFolders.value[folderId]);
  expandedFolders.value[folderId] = !isExpanded;

  if (!isExpanded && folder.has_children && !loadedChildren.value[folderId]) {
    await loadFolderChildren(folderId, folder.drive_id || null);
  }
};

/**
 * Load children of a specific folder
 */
const loadFolderChildren = async (parentId, driveId = null) => {
  try {
    loadingChildren.value[parentId] = true;
    error.value = null;

    const action = isGoogleDrive.value ? "admin/loadGoogleDriveFolderChildren" : "admin/loadOneDriveFolderChildren";

    const payload = {
      companyId: props.companyId,
      parentId: parentId,
    };
    if (isGoogleDrive.value && driveId) {
      payload.driveId = driveId;
    }
    const result = await store.dispatch(action, payload);

    // Add children to folder tree with parent_id.
    // Guard against backend/API edge cases by enforcing parent relationship for real folder nodes.
    const isVirtualParent = parentId === "__shared_drives__" || String(parentId).startsWith("shared_drive::");
    const children = (result.folders || [])
      .filter((f) => {
        if (isVirtualParent) return true;
        const parents = Array.isArray(f.parents) ? f.parents : [];
        return parents.includes(parentId);
      })
      .map((f) => ({
        ...f,
        parent_id: parentId,
        drive_id: f.drive_id || driveId || null,
      }));

    // Add to tree if not already present
    children.forEach((child) => {
      const existing = folderTree.value.find((f) => f.id === child.id);
      if (!existing) {
        folderTree.value.push(child);
      } else {
        // Re-parent existing nodes when discovered via hierarchy traversal.
        // This avoids flattening when the same folder was first loaded from another root source.
        existing.parent_id = parentId;
        existing.parents = child.parents;
        existing.modified_time = child.modified_time;
        existing.created_time = child.created_time;
        existing.drive_id = child.drive_id || driveId || existing.drive_id || null;
      }
    });

    loadedChildren.value[parentId] = true;
  } catch (err) {
    error.value = err.message || "Failed to load folder children";
    console.error(`Error loading folder children for ${parentId}:`, err);
  } finally {
    loadingChildren.value[parentId] = false;
  }
};

// Watch for show prop changes to load data
watch(
  () => props.show,
  (newShow) => {
    if (newShow) {
      // Reset state when modal opens
      searchQuery.value = "";
      error.value = null;
      folderTree.value = [];
      expandedFolders.value = {};
      loadedChildren.value = {};
      loadingChildren.value = {};
      foldersToExpand.value = {};
      parentChains.value = {};
      localLoading.value = true;

      // Preserve the monitored folders from store - don't reset selectedFolders here
      // The watch on monitoredFolders will handle setting the initial selection

      // Load root folders
      loadRootFolders();
    } else {
      localLoading.value = false;
    }
  }
);

// Watch for monitored folders changes to update selection
watch(
  monitoredFolders,
  (newMonitored) => {
    if (newMonitored && newMonitored.length > 0) {
      selectedFolders.value = [...newMonitored];
      console.log("Updated selectedFolders from monitoredFolders:", newMonitored);
    }
  },
  { immediate: true, deep: true }
);

// Methods
const loadRootFolders = async () => {
  try {
    error.value = null;
    localLoading.value = true;

    const action = isGoogleDrive.value ? "admin/loadGoogleDriveFolderChildren" : "admin/loadOneDriveFolderChildren";

    // Load root folders (parent_id = null)
    const result = await store.dispatch(action, {
      companyId: props.companyId,
      parentId: null,
    });

    // Initialize folder tree with root folders
    folderTree.value = result.folders.map((f) => ({
      ...f,
      parent_id: null,
    }));

    // Store folders_to_expand and parent_chains data from backend
    if (result.folders_to_expand) {
      foldersToExpand.value = result.folders_to_expand;
    }
    if (result.parent_chains) {
      parentChains.value = result.parent_chains;
    }

    // Update selectedFolders from the API response if available
    if (result.monitored_folders && result.monitored_folders.length > 0) {
      selectedFolders.value = [...result.monitored_folders];
      console.log("Set selectedFolders from API response:", result.monitored_folders);
    }

    // After loading root folders, load all necessary folders based on folders_to_expand
    await loadFoldersToExpand();
  } catch (err) {
    error.value = err.message || "Failed to load folders";
    console.error(`Error loading ${props.provider} root folders:`, err);
  } finally {
    localLoading.value = false;
  }
};

/**
 * Load all folders that need to be expanded based on the folders_to_expand mapping
 * This ensures the entire tree structure is visible for selected folders
 */
const loadFoldersToExpand = async () => {
  const expandMapping = foldersToExpand.value;
  if (!expandMapping || Object.keys(expandMapping).length === 0) {
    return;
  }

  // Build a list of all folders we need to load, organized by depth
  // We need to load parents before children to maintain proper structure
  const loadQueue = [];

  // Start with root folders
  if (expandMapping.root) {
    for (const folderId of expandMapping.root) {
      loadQueue.push({ parentId: null, folderId, depth: 0 });
    }
  }

  // Process folders level by level
  let currentDepth = 0;
  const maxDepth = 10; // Safety limit

  while (currentDepth < maxDepth) {
    const foldersAtThisDepth = loadQueue.filter((item) => item.depth === currentDepth);

    if (foldersAtThisDepth.length === 0) {
      break; // No more folders to process
    }

    // Load all folders at this depth in parallel
    const loadPromises = [];

    for (const item of foldersAtThisDepth) {
      const { folderId } = item;

      // Check if this folder has children that need to be loaded
      if (expandMapping[folderId] && !loadedChildren.value[folderId]) {
        expandedFolders.value[folderId] = true;
        const node = folderTree.value.find((f) => f.id === folderId);
        loadPromises.push(loadFolderChildren(folderId, node?.drive_id || null));

        // Add this folder's children to the queue for next level
        for (const childId of expandMapping[folderId]) {
          loadQueue.push({ parentId: folderId, folderId: childId, depth: currentDepth + 1 });
        }
      }
    }

    // Wait for all folders at this depth to load
    if (loadPromises.length > 0) {
      try {
        await Promise.all(loadPromises);
      } catch (err) {
        console.error(`Error loading folders at depth ${currentDepth}:`, err);
      }
    }

    currentDepth++;
  }
};

const selectNone = () => {
  selectedFolders.value = [];
};

const saveSelection = async () => {
  try {
    error.value = null;
    saving.value = true;

    // Validation is now done in backend, but we can also check here for better UX
    if (selectedFolders.value.length === 0) {
      error.value = "Please select at least one folder";
      return;
    }

    if (selectedFolders.value.length > 10) {
      error.value = "Maximum 10 folders can be selected";
      return;
    }

    // Never persist virtual tree nodes as monitored folder IDs.
    const folderIdsToSave = selectedFolders.value.filter((id) => {
      const asString = String(id);
      return asString !== "__shared_drives__" && !asString.startsWith("shared_drive::");
    });

    const action = isGoogleDrive.value ? "admin/updateMonitoredFolders" : "admin/updateMonitoredOneDriveFolders";

    const result = await store.dispatch(action, {
      companyId: props.companyId,
      folderIds: folderIdsToSave,
    });

    // Show success message with cleanup info if files were removed
    if (result && result.removed_files > 0) {
      const providerName = isGoogleDrive.value ? "Google Drive" : "OneDrive";
      console.log(`${providerName} folder selection updated. ${result.removed_files} files from unselected folders were removed.`);
    }

    emit("saved", folderIdsToSave, props.provider);
    close();
  } catch (err) {
    // Handle validation errors from backend
    const errorData = err.response?.data;
    if (errorData?.validation_error === "min_folders") {
      error.value = "Please select at least one folder";
    } else if (errorData?.validation_error === "max_folders") {
      error.value = `Maximum 10 folders can be selected. You selected ${errorData.folder_count} folders.`;
    } else {
      error.value = err.message || "Failed to save selection";
    }
    console.error(`Error saving ${props.provider} folder selection:`, err);
  } finally {
    saving.value = false;
  }
};

const close = () => {
  emit("close");
};

const formatDate = (dateString) => {
  if (!dateString) return "";
  return new Date(dateString).toLocaleDateString();
};

// Load root folders when component mounts if modal is shown
onMounted(() => {
  if (props.show) {
    error.value = null;
    localLoading.value = true;
    loadRootFolders();
  }
});
</script>

<style scoped>
.folder-list {
  background-color: var(--bs-body-bg);
}

.folder-item {
  border-color: var(--bs-border-color) !important;
  transition: background-color 0.2s ease;
}

.folder-item:hover {
  background-color: var(--bs-secondary-bg);
}

.folder-item:last-child {
  border-bottom: none !important;
}

.form-check-input:checked {
  background-color: var(--bs-primary);
  border-color: var(--bs-primary);
}

.cursor-pointer {
  cursor: pointer;
}
</style>

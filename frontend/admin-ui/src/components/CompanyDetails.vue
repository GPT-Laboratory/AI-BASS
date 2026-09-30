<template>
  <div v-if="company">
    <!-- Error Alert -->
    <div v-if="error" class="alert alert-danger alert-dismissible fade show mb-3" role="alert">
      <i class="bi bi-exclamation-triangle"></i>
      {{ error }}
      <button type="button" class="btn-close" @click="clearError"></button>
    </div>

    <!-- Company Info -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h2>
        <i v-if="company.environment === 'production'" class="bi bi-building"></i>
        <i v-else-if="company.environment === 'course'" class="bi bi-mortarboard"></i>
        <i v-else class="bi bi-code-square"></i>
        {{ company.name }}
      </h2>
      <button class="btn btn-primary" @click="editCompany">
        <i class="bi bi-pencil"></i>
      </button>
    </div>

    <p>
      <strong>{{ $t("industry") }}:</strong> {{ company.basic_info?.industry }}
    </p>
    <p>
      <strong>{{ $t("founded") }}:</strong> {{ company.basic_info?.founded }}
    </p>
    <p>
      <strong>{{ $t("headquarters") }}:</strong> {{ company.basic_info?.headquarters }}
    </p>

    <hr />

    <!-- Metadata -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h4>{{ $t("metadata") }}</h4>
      <button class="btn btn-success" @click="startAddingMetadata">
        <i class="bi bi-plus-lg"></i>
      </button>
    </div>

    <table class="table table-bordered">
      <thead>
        <tr>
          <th>{{ $t("type") }}</th>
          <th>{{ $t("updated") }}</th>
          <th>{{ $t("rag_sync_status") }}</th>
          <th>{{ $t("actions") }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="doc in metadata" :key="doc._id?.$oid || doc._id">
          <td>{{ $t(doc.type) }}</td>
          <td>{{ formatFinnishDate(doc.updated_at) }}</td>
          <td>
            <span v-if="getRagStatus(doc._id).rag_sync_status === 'waiting' || getRagStatus(doc._id).rag_sync_status === 'processing'">
              <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
            </span>
            <span v-else-if="getRagStatus(doc._id).rag_sync_status === 'inserted'">
              <i class="bi bi-check-circle-fill text-success"></i>
            </span>
            <span v-else-if="getRagStatus(doc._id).rag_sync_status === 'error' || getRagStatus(doc._id).rag_sync_status === 'too_large'">
              <i class="bi bi-x-circle-fill text-danger"></i>
            </span>
            <span v-else>
              <i class="bi bi-question-circle text-muted"></i>
            </span>
          </td>
          <td>
            <button class="btn btn-sm btn-primary" @click="editMetadata(doc)">
              <i class="bi bi-pencil"></i>
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <hr />

    <!-- Manual File Upload -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="d-flex align-items-center">
        <h4 class="mb-0">{{ $t("files") }}</h4>
      </div>
      <div>
        <button class="btn btn-success" @click="triggerFileUpload" :disabled="isUploadingFiles">
          <i class="bi bi-upload"></i>
          <span v-if="!isUploadingFiles"></span>
          <span v-else> {{ $t("uploading") }}...</span>
        </button>
        <input ref="fileInput" type="file" multiple accept=".txt,.csv,.pdf,.docx,.xlsx,.pptx" @change="handleFileUpload" style="display: none" />
      </div>
    </div>

    <div class="card mb-3">
      <div class="card-body">
        <div class="row">
          <div class="col-md-6">
            <p>
              <strong>{{ $t("total_files") }}:</strong>
              <span class="ms-2">{{ manualFiles.length }}</span>
            </p>
          </div>
          <div class="col-md-6">
            <p v-if="company.manual_uploads?.last_upload">
              <strong>{{ $t("last_upload") }}:</strong>
              <span class="ms-2">{{ formatFinnishDateTime(company.manual_uploads.last_upload) }}</span>
            </p>
          </div>
        </div>

        <!-- Manual Files -->
        <div v-if="manualFiles.length > 0" class="mt-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="mb-0">
              <button class="btn btn-link p-0 text-decoration-none text-start" @click="showManualFiles = !showManualFiles" :aria-expanded="showManualFiles">
                <i :class="showManualFiles ? 'bi bi-chevron-down' : 'bi bi-chevron-right'"></i>
                {{ $t("uploaded_files") }} ({{ manualFiles.length }})
              </button>
            </h6>
          </div>

          <div v-show="showManualFiles" class="collapse-content">
            <table class="table table-bordered table-sm">
              <thead>
                <tr>
                  <th>{{ $t("file_name") }}</th>
                  <th>{{ $t("size") }}</th>
                  <th>{{ $t("uploaded") }}</th>
                  <th>{{ $t("rag_sync_status") }}</th>
                  <th>{{ $t("actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in manualFiles" :key="file._id?.$oid || file._id">
                  <td>{{ file.manual_upload?.file_name || file.file_metadata?.file_name || "Unknown file" }}</td>
                  <td>{{ formatFileSize(file.manual_upload?.file_size || file.file_metadata?.file_size) }}</td>
                  <td>{{ formatFinnishDate(file.updated_at) }}</td>
                  <td>
                    <span v-if="getRagStatus(file._id).rag_sync_status === 'waiting' || getRagStatus(file._id).rag_sync_status === 'processing'">
                      <div class="spinner-border spinner-border-sm text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                      </div>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'inserted'">
                      <i class="bi bi-check-circle-fill text-success"></i>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'error' || getRagStatus(file._id).rag_sync_status === 'too_large'">
                      <i class="bi bi-x-circle-fill text-danger"></i>
                    </span>
                    <span v-else>
                      <i class="bi bi-question-circle text-muted"></i>
                    </span>
                  </td>
                  <td>
                    <button class="btn btn-sm btn-primary me-2" @click="editMetadata(file)">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-danger" @click="deleteManualFile(file)" :disabled="isDeletingFiles">
                      <i class="bi bi-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else class="alert alert-info">
          <i class="bi bi-info-circle"></i>
          {{ $t("no_files_uploaded") }}
        </div>
      </div>
    </div>

    <hr />

    <!-- Memories -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="d-flex align-items-center">
        <h4 class="mb-0">{{ $t("memories") || "Memories" }}</h4>
      </div>
    </div>

    <div class="card mb-3">
      <div class="card-body">
        <!-- Memories -->
        <div v-if="memories && memories.length > 0" class="mt-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="mb-0">
              <button class="btn btn-link p-0 text-decoration-none text-start" @click="showMemories = !showMemories" :aria-expanded="showMemories">
                <i :class="showMemories ? 'bi bi-chevron-down' : 'bi bi-chevron-right'"></i>
                {{ $t("memories") || "Memories" }} ({{ memories.length }})
              </button>
            </h6>
          </div>

          <div v-show="showMemories" class="collapse-content">
            <table class="table table-bordered table-sm">
              <thead>
                <tr>
                  <th>{{ $t("memory_content") || "Memory content" }}</th>
                  <th>{{ $t("created") || "Created" }}</th>
                  <th>{{ $t("source_user") || "Source" }}</th>
                  <th>{{ $t("actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="memory in memories" :key="memory._id?.$oid || memory._id">
                  <td>
                    <div class="memory-content">
                      {{ memory.content?.description || "No content" }}
                    </div>
                  </td>
                  <td>{{ formatFinnishDateTime(memory.created_at) }}</td>
                  <td>
                    <small class="text-muted">
                      {{ memory.content?.generated_from_user || "Unknown" }}
                    </small>
                  </td>
                  <td>
                    <button class="btn btn-sm btn-danger" @click="deleteMemory(memory)" :disabled="isDeletingMemories" :title="$t('delete_memory') || 'Delete memory'">
                      <i class="bi bi-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else class="alert alert-info">
          <i class="bi bi-brain"></i>
          {{ $t("no_memories_generated") || "No memories have been generated for this company yet." }}
        </div>
      </div>
    </div>

    <hr />

    <!-- Google Drive Integration -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="d-flex align-items-center">
        <h4 class="mb-0">{{ $t("google_drive") }}</h4>
        <span v-if="company.google_drive?.connected" class="badge bg-success ms-2">{{ $t("connected") }}</span>
      </div>
      <div>
        <button v-if="!company.google_drive?.connected" class="btn btn-info me-2" @click="connectGoogleDrive"><i class="bi bi-cloud-plus"></i></button>
        <button
          v-if="company.google_drive?.connected"
          class="btn btn-warning me-2"
          @click="syncGoogleDrive"
          :disabled="isSyncing || !company.google_drive?.folder_count || company.google_drive.folder_count === 0"
        >
          <i class="bi bi-arrow-repeat"></i>
        </button>
        <button v-if="company.google_drive?.connected" class="btn btn-primary me-2" @click="manageFolders" :disabled="isSyncing">
          <i class="bi bi-folder"></i>
        </button>
        <button v-if="company.google_drive?.connected" class="btn btn-danger" @click="showDisconnectModal = true" :disabled="isSyncing">
          <i class="bi bi-plug"></i>
        </button>
      </div>
    </div>

    <div v-if="company.google_drive?.connected" class="card mb-3">
      <div class="card-body">
        <div v-if="!company.google_drive?.folder_count || company.google_drive.folder_count === 0" class="alert alert-warning mb-3">
          <i class="bi bi-exclamation-triangle"></i>
          <strong>{{ $t("no_folders_selected") }}:</strong> {{ $t("no_folders_selected_sync_warning") }}
        </div>
        <div class="row">
          <div class="col-md-6">
            <p>
              <strong>{{ $t("last_sync") }}:</strong>
              <span v-if="isSyncing" class="text-muted ms-2">
                <div class="spinner-border spinner-border-sm me-2" role="status">
                  <span class="visually-hidden">Loading...</span>
                </div>
                {{ $t("sync_in_progress") }}
              </span>
              <span v-else class="ms-2">
                {{ company.google_drive.last_sync ? formatFinnishDateTime(company.google_drive.last_sync) : $t("never") }}
                <i v-if="company.google_drive.last_sync && lastSyncStatus === 'success'" class="bi bi-check-circle-fill text-success ms-2"></i>
                <i v-if="company.google_drive.last_sync && lastSyncStatus === 'error'" class="bi bi-x-circle-fill text-danger ms-2"></i>
                <i v-if="company.google_drive.last_sync && !lastSyncStatus" class="bi bi-check-circle-fill text-success ms-2"></i>
              </span>
            </p>
            <p v-if="company.google_drive?.email_address">
              <strong>{{ $t("email_address") }}:</strong>
              <span class="ms-2">{{ company.google_drive.email_address }}</span>
            </p>
          </div>
          <div class="col-md-6">
            <p>
              <strong>{{ $t("monitored_folders") }}:</strong>
              <span class="ms-2">{{ company.google_drive.folder_count || 0 }}</span>
              <span v-if="!company.google_drive?.folder_count || company.google_drive.folder_count === 0" class="badge bg-warning ms-2">
                <i class="bi bi-exclamation-triangle"></i> {{ $t("none_selected") }}
              </span>
            </p>
            <p>
              <strong>{{ $t("synced_files") }}:</strong>
              <span class="ms-2">{{ company.google_drive.file_count || 0 }}</span>
            </p>
          </div>
        </div>

        <!-- Google Drive Files -->
        <div v-if="googleDriveFiles.length > 0" class="mt-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="mb-0">
              <button class="btn btn-link p-0 text-decoration-none text-start" @click="showGoogleDriveFiles = !showGoogleDriveFiles" :aria-expanded="showGoogleDriveFiles">
                <i :class="showGoogleDriveFiles ? 'bi bi-chevron-down' : 'bi bi-chevron-right'"></i>
                {{ $t("synced_files") }} ({{ googleDriveFiles.length }})
              </button>
            </h6>
          </div>

          <div v-show="showGoogleDriveFiles" class="collapse-content">
            <table class="table table-bordered table-sm">
              <thead>
                <tr>
                  <th>{{ $t("file_name") }}</th>
                  <th>{{ $t("updated") }}</th>
                  <th>{{ $t("rag_sync_status") }}</th>
                  <th>{{ $t("actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in googleDriveFiles" :key="file._id?.$oid || file._id">
                  <td>{{ file.google_drive?.file_name || file.content?.file_name || "Unknown file" }}</td>
                  <td>{{ formatFinnishDate(file.updated_at) }}</td>
                  <td>
                    <span v-if="getRagStatus(file._id).rag_sync_status === 'waiting' || getRagStatus(file._id).rag_sync_status === 'processing'">
                      <div class="spinner-border spinner-border-sm text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                      </div>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'inserted'">
                      <i class="bi bi-check-circle-fill text-success"></i>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'error' || getRagStatus(file._id).rag_sync_status === 'too_large'">
                      <i class="bi bi-x-circle-fill text-danger"></i>
                    </span>
                    <span v-else>
                      <i class="bi bi-question-circle text-muted"></i>
                    </span>
                  </td>
                  <td>
                    <button class="btn btn-sm btn-primary" @click="editMetadata(file)">
                      <i class="bi bi-pencil"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="alert alert-info">
      <i class="bi bi-info-circle"></i>
      {{ $t("google_drive_not_connected") }}
    </div>

    <hr />

    <!-- OneDrive Integration -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="d-flex align-items-center">
        <h4 class="mb-0">{{ $t("onedrive") }}</h4>
        <span v-if="company.onedrive?.connected" class="badge bg-success ms-2">{{ $t("connected") }}</span>
      </div>
      <div>
        <button v-if="!company.onedrive?.connected" class="btn btn-info me-2" @click="connectOneDrive"><i class="bi bi-cloud-plus"></i></button>
        <button
          v-if="company.onedrive?.connected"
          class="btn btn-warning me-2"
          @click="syncOneDrive"
          :disabled="isSyncingOneDrive || !company.onedrive?.folder_count || company.onedrive.folder_count === 0"
        >
          <i class="bi bi-arrow-repeat"></i>
        </button>
        <button v-if="company.onedrive?.connected" class="btn btn-primary me-2" @click="manageOneDriveFolders" :disabled="isSyncingOneDrive">
          <i class="bi bi-folder"></i>
        </button>
        <button v-if="company.onedrive?.connected" class="btn btn-danger" @click="showOneDriveDisconnectModal = true" :disabled="isSyncingOneDrive">
          <i class="bi bi-plug"></i>
        </button>
      </div>
    </div>

    <div v-if="company.onedrive?.connected" class="card mb-3">
      <div class="card-body">
        <div v-if="!company.onedrive?.folder_count || company.onedrive.folder_count === 0" class="alert alert-warning mb-3">
          <i class="bi bi-exclamation-triangle"></i>
          {{ $t("no_onedrive_folders_selected") }}
        </div>
        <div class="row">
          <div class="col-md-6">
            <p>
              <strong>{{ $t("last_sync") }}:</strong>
              <span v-if="isSyncingOneDrive" class="text-muted ms-2">
                <div class="spinner-border spinner-border-sm me-2" role="status">
                  <span class="visually-hidden">Loading...</span>
                </div>
                {{ $t("sync_in_progress") }}
              </span>
              <span v-else class="ms-2">
                {{ company.onedrive.last_sync ? formatFinnishDateTime(company.onedrive.last_sync) : $t("never") }}
                <i v-if="company.onedrive.last_sync && lastOneDriveSyncStatus === 'success'" class="bi bi-check-circle-fill text-success ms-2"></i>
                <i v-if="company.onedrive.last_sync && lastOneDriveSyncStatus === 'error'" class="bi bi-x-circle-fill text-danger ms-2"></i>
                <i v-if="company.onedrive.last_sync && !lastOneDriveSyncStatus" class="bi bi-check-circle-fill text-success ms-2"></i>
              </span>
            </p>
            <p>
              <strong>{{ $t("email_address") }}:</strong>
              <span class="ms-2">{{ company.onedrive.email_address }}</span>
            </p>
          </div>
          <div class="col-md-6">
            <p>
              <strong>{{ $t("monitored_folders") }}:</strong>
              <span class="ms-2">{{ company.onedrive.folder_count || 0 }}</span>
              <span v-if="!company.onedrive?.folder_count || company.onedrive.folder_count === 0" class="badge bg-warning ms-2">
                {{ $t("select_folders") }}
              </span>
            </p>
            <p>
              <strong>{{ $t("synced_files") }}:</strong>
              <span class="ms-2">{{ company.onedrive.file_count || 0 }}</span>
            </p>
          </div>
        </div>

        <!-- OneDrive Files -->
        <div v-if="oneDriveFiles.length > 0" class="mt-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="mb-0">
              <button class="btn btn-link p-0 text-decoration-none text-start" @click="showOneDriveFiles = !showOneDriveFiles" :aria-expanded="showOneDriveFiles">
                <i :class="showOneDriveFiles ? 'bi bi-chevron-down' : 'bi bi-chevron-right'"></i>
                {{ $t("synced_files") }} ({{ oneDriveFiles.length }})
              </button>
            </h6>
          </div>

          <div v-show="showOneDriveFiles" class="collapse-content">
            <table class="table table-bordered table-sm">
              <thead>
                <tr>
                  <th>{{ $t("file_name") }}</th>
                  <th>{{ $t("updated") }}</th>
                  <th>{{ $t("rag_sync_status") }}</th>
                  <th>{{ $t("actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in oneDriveFiles" :key="file._id?.$oid || file._id">
                  <td>{{ file.content?.file_name || "Unknown file" }}</td>
                  <td>{{ formatFinnishDate(file.updated_at) }}</td>
                  <td>
                    <span v-if="getRagStatus(file._id).rag_sync_status === 'waiting' || getRagStatus(file._id).rag_sync_status === 'processing'">
                      <div class="spinner-border spinner-border-sm text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                      </div>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'inserted'">
                      <i class="bi bi-check-circle-fill text-success"></i>
                    </span>
                    <span v-else-if="getRagStatus(file._id).rag_sync_status === 'error' || getRagStatus(file._id).rag_sync_status === 'too_large'">
                      <i class="bi bi-x-circle-fill text-danger"></i>
                    </span>
                    <span v-else>
                      <i class="bi bi-question-circle text-muted"></i>
                    </span>
                  </td>
                  <td>
                    <button class="btn btn-sm btn-primary" @click="editMetadata(file)">
                      <i class="bi bi-pencil"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="alert alert-info">
      <i class="bi bi-info-circle"></i>
      {{ $t("onedrive_not_connected") }}
    </div>

    <hr />

    <!-- Email Integration -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="d-flex align-items-center">
        <h4 class="mb-0">{{ $t("email_integration") }}</h4>
        <span v-if="company.email_integration?.connected" class="badge bg-success ms-2">{{ $t("connected") }}</span>
      </div>
      <div>
        <div v-if="!company.email_integration?.connected" class="d-flex gap-2">
          <button class="btn btn-danger me-2" @click="connectEmail('gmail')" style="background-color: #ea4335; border-color: #ea4335">
            <i class="bi bi-google"></i>
          </button>
          <button class="btn btn-primary me-2" @click="connectEmail('microsoft')" style="background-color: #0078d4; border-color: #0078d4">
            <i class="bi bi-microsoft"></i>
          </button>
          <button
            class="btn btn-secondary me-2"
            @click="
              showGenericIMAPForm = true;
              showEmailConnectionModal = true;
            "
          >
            <i class="bi bi-envelope"></i>
          </button>
        </div>
        <button v-if="company.email_integration?.connected" class="btn btn-warning me-2" @click="syncEmails" :disabled="isSyncingEmails">
          <i class="bi bi-arrow-repeat"></i>
        </button>
        <button v-if="company.email_integration?.connected" class="btn btn-danger" @click="showEmailDisconnectModal = true">
          <i class="bi bi-plug"></i>
        </button>
      </div>
    </div>

    <div v-if="company.email_integration?.connected" class="card mb-3">
      <div class="card-body">
        <div class="row">
          <div class="col-md-6">
            <p>
              <strong>{{ $t("last_sync") }}:</strong>
              <span v-if="isSyncingEmails" class="text-muted ms-2">
                <div class="spinner-border spinner-border-sm me-2" role="status">
                  <span class="visually-hidden">Loading...</span>
                </div>
                {{ $t("sync_in_progress") }}
              </span>
              <span v-else class="ms-2">
                {{ company.email_integration.last_sync ? formatFinnishDateTime(company.email_integration.last_sync) : $t("never") }}
                <i v-if="company.email_integration.last_sync && lastEmailSyncStatus === 'success'" class="bi bi-check-circle-fill text-success ms-2"></i>
                <i v-if="company.email_integration.last_sync && lastEmailSyncStatus === 'error'" class="bi bi-x-circle-fill text-danger ms-2"></i>
                <i v-if="company.email_integration.last_sync && !lastEmailSyncStatus" class="bi bi-check-circle-fill text-success ms-2"></i>
              </span>
            </p>
            <p>
              <strong>{{ $t("email_provider") }}:</strong>
              <span class="ms-2">{{ company.email_integration.provider?.charAt(0).toUpperCase() + company.email_integration.provider?.slice(1) }}</span>
            </p>
            <p>
              <strong>{{ $t("email_address") }}:</strong>
              <span class="ms-2">{{ company.email_integration.email_address }}</span>
            </p>
          </div>
          <div class="col-md-6">
            <p>
              <strong>{{ $t("sync_folders") }}:</strong>
              <span class="ms-2">{{ (company.email_integration.settings?.sync_folders || []).join(", ") || "INBOX" }}</span>
            </p>
            <p>
              <strong>{{ $t("total_emails_synced") }}:</strong>
              <span class="ms-2">{{ company.email_integration.stats?.total_emails_synced || 0 }}</span>
            </p>
            <p>
              <strong>{{ $t("last_sync_count") }}:</strong>
              <span class="ms-2">{{ company.email_integration.stats?.last_sync_count || 0 }}</span>
            </p>
          </div>
        </div>

        <!-- Email Files -->
        <div v-if="emails.length > 0" class="mt-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="mb-0">
              <button class="btn btn-link p-0 text-decoration-none text-start" @click="showEmails = !showEmails" :aria-expanded="showEmails">
                <i :class="showEmails ? 'bi bi-chevron-down' : 'bi bi-chevron-right'"></i>
                {{ $t("synced_emails") }} ({{ emails.length }})
              </button>
            </h6>
          </div>

          <div v-show="showEmails" class="collapse-content">
            <table class="table table-bordered table-sm">
              <thead>
                <tr>
                  <th>{{ $t("subject") }}</th>
                  <th>{{ $t("sender") }}</th>
                  <th>{{ $t("date") }}</th>
                  <th>{{ $t("rag_sync_status") }}</th>
                  <th>{{ $t("actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="email in emails" :key="email._id?.$oid || email._id">
                  <td>{{ email.content?.subject || "No subject" }}</td>
                  <td>{{ email.content?.sender || "Unknown" }}</td>
                  <td>{{ formatFinnishDate(email.content?.date) }}</td>
                  <td>
                    <span v-if="getRagStatus(email._id).rag_sync_status === 'waiting' || getRagStatus(email._id).rag_sync_status === 'processing'">
                      <div class="spinner-border spinner-border-sm text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                      </div>
                    </span>
                    <span v-else-if="getRagStatus(email._id).rag_sync_status === 'inserted'">
                      <i class="bi bi-check-circle-fill text-success"></i>
                    </span>
                    <span v-else-if="getRagStatus(email._id).rag_sync_status === 'error' || getRagStatus(email._id).rag_sync_status === 'too_large'">
                      <i class="bi bi-x-circle-fill text-danger"></i>
                    </span>
                    <span v-else>
                      <i class="bi bi-question-circle text-muted"></i>
                    </span>
                  </td>
                  <td>
                    <button class="btn btn-sm btn-primary" @click="editMetadata(email)">
                      <i class="bi bi-pencil"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="alert alert-info">
      <i class="bi bi-info-circle"></i>
      {{ $t("email_not_connected") }}
    </div>
    <div class="alert alert-warning">
      <i class="bi bi-exclamation-triangle"></i>
      {{ $t("email_integration_warning") }}
    </div>
    <hr />

    <!-- Users -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h4>{{ $t("users") }}</h4>
      <button v-if="showCreateUser" class="btn btn-success" @click="startAddingUser">
        <i class="bi bi-plus-lg"></i>
      </button>
    </div>

    <table class="table table-bordered">
      <thead>
        <tr>
          <th>{{ $t("first_name") }}</th>
          <th>{{ $t("last_name") }}</th>
          <th>{{ $t("phone_number") }}</th>
          <th>{{ $t("actions") }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user._id?.$oid || user._id">
          <td>{{ user.first_name }}</td>
          <td>{{ user.last_name }}</td>
          <td>{{ user.phone_number }}</td>
          <td>
            <button class="btn btn-sm btn-primary" @click="editUser(user)">
              <i class="bi bi-pencil"></i>
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <hr />

    <!-- External API Key -->
    <div class="card mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h4 class="mb-0">{{ $t("external_api_key") || "External API key" }}</h4>
          <div class="btn-group">
            <button v-if="apiKey" class="btn btn-outline-secondary btn-sm" @click="copyApiKey" :disabled="apiKeyBusy">
              <i class="bi bi-clipboard"></i> {{ $t("copy") || "Copy" }}
            </button>
            <button v-if="apiKey" class="btn btn-warning btn-sm" @click="regenerateApiKey" :disabled="apiKeyBusy">
              <i class="bi bi-arrow-clockwise"></i> {{ $t("regenerate") || "Regenerate" }}
            </button>
            <button v-if="apiKey" class="btn btn-outline-danger btn-sm" @click="revokeApiKey" :disabled="apiKeyBusy">
              <i class="bi bi-x-circle"></i> {{ $t("revoke") || "Revoke" }}
            </button>
            <button v-else class="btn btn-success btn-sm" @click="regenerateApiKey" :disabled="apiKeyBusy">
              <i class="bi bi-key"></i> {{ $t("generate") || "Generate" }}
            </button>
          </div>
        </div>

        <p class="text-muted small mb-2">
          {{ $t("external_api_key_help") || "Use this key with the REST /api/chat endpoint (header X-API-Key). Keep it secret." }}
        </p>

        <div v-if="apiKeyError" class="alert alert-danger py-2">{{ apiKeyError }}</div>
        <div v-if="apiKeyMessage" class="alert alert-success py-2">{{ apiKeyMessage }}</div>

        <div class="input-group">
          <input type="text" class="form-control" :value="apiKey || $t('no_api_key') || 'No API key yet'" readonly />
          <span class="input-group-text" v-if="apiKeyCreatedAt">
            {{ $t("created") || "Created" }}: {{ formatFinnishDateTime(apiKeyCreatedAt) }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <div v-else>
    <p>{{ $t("loading") }}</p>
  </div>

  <!-- Google Drive Disconnect Modal -->
  <div v-if="showDisconnectModal" class="modal fade show" style="display: block; background-color: rgba(0, 0, 0, 0.5)" tabindex="-1">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ $t("disconnect_google_drive") }}</h5>
          <button type="button" class="btn-close" @click="showDisconnectModal = false" :disabled="isDisconnectingGoogleDrive"></button>
        </div>
        <div class="modal-body">
          <p>{{ $t("disconnect_google_drive_warning") }}</p>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="removeSyncedFiles" v-model="removeSyncedFiles" />
            <label class="form-check-label" for="removeSyncedFiles">
              {{ $t("remove_synced_files") }}
            </label>
          </div>
          <small class="text-muted">{{ $t("remove_synced_files_explanation") }}</small>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showDisconnectModal = false" :disabled="isDisconnectingGoogleDrive">
            {{ $t("cancel") }}
          </button>
          <button type="button" class="btn btn-danger" @click="disconnectGoogleDrive" :disabled="isDisconnectingGoogleDrive">
            <span v-if="isDisconnectingGoogleDrive" class="spinner-border spinner-border-sm me-2" role="status"></span>
            <i v-else class="bi bi-plug"></i>
            {{ $t("disconnect") }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Google Drive Folder Manager -->
  <!-- Cloud Drive Folder Manager -->
  <CloudFolderManager :show="showFolderManager" :company-id="companyId" provider="google_drive" @close="onFolderManagerClose" @saved="onCloudFoldersSaved" />

  <!-- OneDrive Disconnect Modal -->
  <div v-if="showOneDriveDisconnectModal" class="modal fade show" style="display: block; background-color: rgba(0, 0, 0, 0.5)" tabindex="-1">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ $t("disconnect_onedrive") }}</h5>
          <button type="button" class="btn-close" @click="showOneDriveDisconnectModal = false" :disabled="isDisconnectingOneDrive"></button>
        </div>
        <div class="modal-body">
          <p>{{ $t("disconnect_onedrive_warning") }}</p>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="removeSyncedOneDriveFiles" v-model="removeSyncedOneDriveFiles" />
            <label class="form-check-label" for="removeSyncedOneDriveFiles">
              {{ $t("remove_synced_files") }}
            </label>
          </div>
          <small class="text-muted">{{ $t("remove_synced_files_explanation") }}</small>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showOneDriveDisconnectModal = false" :disabled="isDisconnectingOneDrive">
            {{ $t("cancel") }}
          </button>
          <button type="button" class="btn btn-danger" @click="disconnectOneDrive" :disabled="isDisconnectingOneDrive">
            <span v-if="isDisconnectingOneDrive" class="spinner-border spinner-border-sm me-2" role="status"></span>
            <i v-else class="bi bi-plug"></i>
            {{ $t("disconnect") }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- OneDrive Folder Manager -->
  <CloudFolderManager :show="showOneDriveFolderManager" :company-id="companyId" provider="onedrive" @close="onOneDriveFolderManagerClose" @saved="onCloudFoldersSaved" />

  <!-- Email Connection Modal -->
  <div v-if="showEmailConnectionModal" class="modal fade show" style="display: block; background-color: rgba(0, 0, 0, 0.5)" tabindex="-1">
    <div class="modal-dialog modal-lg">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ $t("connect_email_account") }}</h5>
          <button type="button" class="btn-close" @click="closeEmailConnectionModal"></button>
        </div>
        <div class="modal-body">
          <div v-if="!showGenericIMAPForm" class="row">
            <div class="col-md-4">
              <button class="btn btn-outline-primary w-100 mb-2" @click="connectEmail('gmail')">
                <i class="bi bi-google"></i><br />
                Gmail
              </button>
            </div>
            <div class="col-md-4">
              <button class="btn btn-outline-primary w-100 mb-2" @click="connectEmail('microsoft')">
                <i class="bi bi-microsoft"></i><br />
                Outlook/Microsoft 365
              </button>
            </div>
            <div class="col-md-4">
              <button class="btn btn-outline-primary w-100 mb-2" @click="showGenericIMAPForm = true">
                <i class="bi bi-envelope"></i><br />
                Other Email Provider
              </button>
            </div>
          </div>

          <!-- Generic IMAP Form -->
          <div v-if="showGenericIMAPForm" class="mt-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <h6>{{ $t("generic_imap_setup") }}</h6>
              <button type="button" class="btn btn-sm btn-secondary" @click="showGenericIMAPForm = false"><i class="bi bi-arrow-left"></i> {{ $t("back") }}</button>
            </div>
            <form @submit.prevent="connectGenericIMAP">
              <div class="mb-3">
                <label class="form-label">{{ $t("email_address") }}</label>
                <input type="email" class="form-control" v-model="imapForm.email" required />
              </div>
              <div class="mb-3">
                <label class="form-label">{{ $t("password") }}</label>
                <input type="password" class="form-control" v-model="imapForm.password" required />
                <small class="text-muted">{{ $t("imap_password_help") }}</small>
              </div>
              <div class="mb-3">
                <label class="form-label">{{ $t("imap_server") }}</label>
                <input type="text" class="form-control" v-model="imapForm.server" placeholder="imap.example.com" required />
              </div>
              <div class="row">
                <div class="col-md-6">
                  <label class="form-label">{{ $t("port") }}</label>
                  <input type="number" class="form-control" v-model="imapForm.port" value="993" />
                </div>
                <div class="col-md-6">
                  <div class="form-check mt-4">
                    <input class="form-check-input" type="checkbox" v-model="imapForm.ssl" checked />
                    <label class="form-check-label">{{ $t("use_ssl") }}</label>
                  </div>
                </div>
              </div>
              <div class="mt-3">
                <button type="submit" class="btn btn-primary" :disabled="isConnectingEmail">
                  <span v-if="isConnectingEmail" class="spinner-border spinner-border-sm me-2"></span>
                  {{ $t("connect") }}
                </button>
              </div>
            </form>
          </div>
        </div>
        <div class="modal-footer" v-if="!showGenericIMAPForm">
          <button type="button" class="btn btn-secondary" @click="closeEmailConnectionModal">
            {{ $t("cancel") }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Email Disconnect Modal -->
  <div v-if="showEmailDisconnectModal" class="modal fade show" style="display: block; background-color: rgba(0, 0, 0, 0.5)" tabindex="-1">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ $t("disconnect_email") }}</h5>
          <button type="button" class="btn-close" @click="showEmailDisconnectModal = false" :disabled="isDisconnectingEmail"></button>
        </div>
        <div class="modal-body">
          <p>{{ $t("disconnect_email_warning") }}</p>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="removeSyncedEmails" v-model="removeSyncedEmails" />
            <label class="form-check-label" for="removeSyncedEmails">
              {{ $t("remove_synced_emails") }}
            </label>
          </div>
          <small class="text-muted">{{ $t("remove_synced_emails_explanation") }}</small>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showEmailDisconnectModal = false" :disabled="isDisconnectingEmail">
            {{ $t("cancel") }}
          </button>
          <button type="button" class="btn btn-danger" @click="disconnectEmail" :disabled="isDisconnectingEmail">
            <span v-if="isDisconnectingEmail" class="spinner-border spinner-border-sm me-2" role="status"></span>
            <i v-else class="bi bi-plug"></i>
            {{ $t("disconnect") }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watchEffect, ref, nextTick } from "vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
import { useRoute, useRouter } from "vue-router";
import { useStore } from "vuex";
import { decodeJwt } from "../utils/jwt";
import { useApi } from "../composables/useApi";
import CloudFolderManager from "./CloudFolderManager.vue";

const route = useRoute();
const router = useRouter();
const store = useStore();

const companyId = route.params.id;

// Reactive variables for modals
const showDisconnectModal = ref(false);
const removeSyncedFiles = ref(false);
const showFolderManager = ref(false);
const isSyncing = ref(false);
const lastSyncStatus = ref(null); // null, 'success', or 'error'
const showGoogleDriveFiles = ref(false); // For collapsible Google Drive files section
const isDisconnectingGoogleDrive = ref(false); // Loading state for disconnect

// OneDrive integration reactive variables
const showOneDriveDisconnectModal = ref(false);
const removeSyncedOneDriveFiles = ref(false);
const showOneDriveFolderManager = ref(false);
const isSyncingOneDrive = ref(false);
const lastOneDriveSyncStatus = ref(null); // null, 'success', or 'error'
const showOneDriveFiles = ref(false); // For collapsible OneDrive files section
const isDisconnectingOneDrive = ref(false); // Loading state for disconnect

// Email integration reactive variables
const showEmailConnectionModal = ref(false);
const showEmailDisconnectModal = ref(false);
const showGenericIMAPForm = ref(false);
const removeSyncedEmails = ref(false);
const isSyncingEmails = ref(false);
const isConnectingEmail = ref(false);
const lastEmailSyncStatus = ref(null); // null, 'success', or 'error'
const showEmails = ref(false); // For collapsible emails section
const isDisconnectingEmail = ref(false); // Loading state for disconnect

// Manual file upload reactive variables
const showManualFiles = ref(false); // For collapsible manual files section
const isUploadingFiles = ref(false);
const isDeletingFiles = ref(false);
const fileInput = ref(null);

// AI-generated memories reactive variables
const showMemories = ref(false); // For collapsible memories section
const isDeletingMemories = ref(false);

// External API key state
const apiKeyBusy = ref(false);
const apiKeyMessage = ref("");
const apiKeyError = ref("");

// RAG sync status tracking
const ragStatusMap = ref(new Map()); // Map of document _id -> { rag_sync_status, rag_sync_error }
let ragStatusPollInterval = null;

// IMAP form data
const imapForm = ref({
  email: "",
  password: "",
  server: "",
  port: 993,
  ssl: true,
});

const company = computed(() => store.state.admin.selectedCompany);
const metadata = computed(() =>
  store.state.admin.companyMetadata.filter(
    (m) => m.type !== "google_drive_file" && m.type !== "onedrive_file" && m.type !== "email" && m.type !== "manual_upload_file" && m.type !== "ai_generated_memory"
  )
);
const googleDriveFiles = computed(() => store.state.admin.companyMetadata.filter((m) => m.type === "google_drive_file"));
const oneDriveFiles = computed(() => store.state.admin.companyMetadata.filter((m) => m.type === "onedrive_file"));
const emails = computed(() => store.state.admin.companyMetadata.filter((m) => m.type === "email"));
const manualFiles = computed(() => store.state.admin.companyMetadata.filter((m) => m.type === "manual_upload_file"));
const memories = computed(() => store.state.admin.companyMemories);
const memoryStats = computed(() => store.state.admin.memoryStats);
const users = computed(() => store.state.admin.users);
const error = computed(() => store.state.admin.error);
const isLoading = computed(() => store.state.admin.loading);
const apiKey = computed(() => store.state.admin.selectedCompany?.api_key || "");
const apiKeyCreatedAt = computed(() => store.state.admin.selectedCompany?.api_key_created_at || "");
const showCreateUser = computed(() => {
  const token = store.state.admin.authToken || localStorage.getItem("authToken");
  const claims = decodeJwt(token);
  return claims?.role === "admin" && claims?.exp > Date.now() / 1000;
});

// Utility functions for Finnish datetime formatting
const formatFinnishDateTime = (dateString) => {
  if (!dateString) return "";

  try {
    let utcDate;

    // Handle MongoDB BSON date format: { "$date": "ISO_STRING" }
    if (typeof dateString === "object" && dateString.$date) {
      utcDate = new Date(dateString.$date);
    } else if (typeof dateString === "string") {
      // Handle different date formats more robustly
      if (dateString.includes("+") || dateString.includes("Z") || dateString.includes("-", 19)) {
        // Already has timezone info (Z, +XX:XX, or -XX:XX at position 19 or later), parse directly
        utcDate = new Date(dateString);
      } else {
        // No timezone info, assume UTC and add Z
        utcDate = new Date(dateString + "Z");
      }
    } else {
      // Try to parse as-is (could be Date object)
      utcDate = new Date(dateString);
    }

    // Check if the date is valid
    if (isNaN(utcDate.getTime())) {
      console.warn("Invalid date string:", dateString);
      return dateString; // Return original string if parsing fails
    }

    // Convert to Finnish time (UTC+3 in summer, UTC+2 in winter)
    // For simplicity, we'll use +3 hours (summer time)
    const finnishTime = new Date(utcDate.getTime() + 3 * 60 * 60 * 1000);

    // Format manually
    const year = finnishTime.getUTCFullYear();
    const month = String(finnishTime.getUTCMonth() + 1).padStart(2, "0");
    const day = String(finnishTime.getUTCDate()).padStart(2, "0");
    const hour = String(finnishTime.getUTCHours()).padStart(2, "0");
    const minute = String(finnishTime.getUTCMinutes()).padStart(2, "0");
    const second = String(finnishTime.getUTCSeconds()).padStart(2, "0");

    return `${day}.${month}.${year} ${hour}:${minute}:${second}`;
  } catch (error) {
    console.warn("Error formatting date:", dateString, error);
    return dateString; // Return original string if any error occurs
  }
};

const formatFinnishDate = (dateString) => {
  if (!dateString) return "";

  try {
    let utcDate;

    // Handle MongoDB BSON date format: { "$date": "ISO_STRING" }
    if (typeof dateString === "object" && dateString.$date) {
      utcDate = new Date(dateString.$date);
    } else if (typeof dateString === "string") {
      // Handle different date formats more robustly
      if (dateString.includes("+") || dateString.includes("Z") || dateString.includes("-", 19)) {
        // Already has timezone info (Z, +XX:XX, or -XX:XX at position 19 or later), parse directly
        utcDate = new Date(dateString);
      } else {
        // No timezone info, assume UTC and add Z
        utcDate = new Date(dateString + "Z");
      }
    } else {
      // Try to parse as-is (could be Date object)
      utcDate = new Date(dateString);
    }

    // Check if the date is valid
    if (isNaN(utcDate.getTime())) {
      console.warn("Invalid date string:", dateString);
      return dateString; // Return original string if parsing fails
    }

    // Convert to Finnish time (UTC+3 in summer, UTC+2 in winter)
    // For simplicity, we'll use +3 hours (summer time)
    const finnishTime = new Date(utcDate.getTime() + 3 * 60 * 60 * 1000);

    // Format manually
    const year = finnishTime.getUTCFullYear();
    const month = String(finnishTime.getUTCMonth() + 1).padStart(2, "0");
    const day = String(finnishTime.getUTCDate()).padStart(2, "0");

    return `${day}.${month}.${year}`;
  } catch (error) {
    console.warn("Error formatting date:", dateString, error);
    return dateString; // Return original string if any error occurs
  }
};

const fetchCompany = async () => {
  await store.dispatch("admin/loadCompany", companyId);
};

const fetchMetadata = async (id) => {
  if (id) {
    await store.dispatch("admin/loadMetadataByCompanyId", id);
  }
};

const fetchUsers = async (id) => {
  if (id) {
    await store.dispatch("admin/loadUsersByCompanyId", id);
  }
};

const fetchMemories = async (id) => {
  if (id) {
    await store.dispatch("admin/loadMemoriesByCompanyId", id);
    await store.dispatch("admin/loadMemoryStats", id);
  }
};

const loadApiKey = async () => {
  apiKeyBusy.value = true;
  apiKeyError.value = "";
  try {
    await store.dispatch("admin/fetchCompanyApiKey", companyId);
  } catch (err) {
    console.error("Failed to fetch API key:", err);
    apiKeyError.value = t("failed_load_api_key") || "Failed to load API key";
  } finally {
    apiKeyBusy.value = false;
  }
};

const regenerateApiKey = async () => {
  if (apiKeyBusy.value) return;
  if (apiKey.value && !confirm(t("confirm_regenerate_api_key") || "Regenerate API key? This will invalidate the old one.")) return;
  apiKeyBusy.value = true;
  apiKeyError.value = "";
  apiKeyMessage.value = "";
  try {
    const res = await store.dispatch("admin/regenerateCompanyApiKey", companyId);
    apiKeyMessage.value = t("api_key_generated") || "API key generated";
    if (res?.api_key && navigator?.clipboard) {
      await navigator.clipboard.writeText(res.api_key);
    }
  } catch (err) {
    console.error("Failed to regenerate API key:", err);
    apiKeyError.value = t("failed_regenerate_api_key") || "Failed to regenerate API key";
  } finally {
    apiKeyBusy.value = false;
  }
};

const revokeApiKey = async () => {
  if (apiKeyBusy.value) return;
  if (!apiKey.value) return;
  if (!confirm(t("confirm_revoke_api_key") || "Revoke this API key? Clients using it will stop working.")) return;
  apiKeyBusy.value = true;
  apiKeyError.value = "";
  apiKeyMessage.value = "";
  try {
    await store.dispatch("admin/revokeCompanyApiKey", companyId);
    apiKeyMessage.value = t("api_key_revoked") || "API key revoked";
  } catch (err) {
    console.error("Failed to revoke API key:", err);
    apiKeyError.value = t("failed_revoke_api_key") || "Failed to revoke API key";
  } finally {
    apiKeyBusy.value = false;
  }
};

const copyApiKey = async () => {
  if (!apiKey.value) return;
  apiKeyError.value = "";
  apiKeyMessage.value = "";
  try {
    await navigator.clipboard.writeText(apiKey.value);
    apiKeyMessage.value = t("copied") || "Copied";
  } catch (err) {
    console.error("Failed to copy API key:", err);
    apiKeyError.value = t("failed_copy_api_key") || "Failed to copy API key";
  }
};

// Fetch RAG sync status for all documents
const fetchRagStatus = async () => {
  if (!companyId) return;

  try {
    const token = store.state.admin.authToken || localStorage.getItem("authToken");
    if (!token) return; // No token, skip polling

    const { api } = useApi(token);
    const response = await api.get(`/metadata/company/${companyId}/rag-status`);

    if (response.data && Array.isArray(response.data)) {
      // Update the status map
      const newMap = new Map();
      response.data.forEach((item) => {
        newMap.set(item._id, {
          rag_sync_status: item.rag_sync_status || "unknown",
        });
      });
      ragStatusMap.value = newMap;

      // Smart polling: Stop if all documents are inserted or have errors (no waiting/processing)
      const hasActiveSync = Array.from(newMap.values()).some((status) => status.rag_sync_status === "waiting" || status.rag_sync_status === "processing");

      // If nothing is syncing, stop polling
      if (!hasActiveSync && ragStatusPollInterval) {
        console.log("All RAG syncs complete, stopping polling");
        stopRagStatusPolling();
      }
    }
  } catch (error) {
    console.error("Failed to fetch RAG sync status:", error);
  }
};

// Start polling for RAG status updates
const startRagStatusPolling = () => {
  // Don't start if already polling
  if (ragStatusPollInterval) {
    console.log("RAG status polling already active, skipping start");
    return;
  }

  // Fetch immediately
  fetchRagStatus();

  // Then poll every 10 seconds
  ragStatusPollInterval = setInterval(() => {
    fetchRagStatus();
  }, 10000);
};

// Stop polling
const stopRagStatusPolling = () => {
  if (ragStatusPollInterval) {
    clearInterval(ragStatusPollInterval);
    ragStatusPollInterval = null;
  }
};

// Helper to get RAG status for a document
const getRagStatus = (docId) => {
  const id = docId?.$oid || docId;
  return ragStatusMap.value.get(id) || { rag_sync_status: "unknown" };
};

onMounted(async () => {
  // Ensure company data is loaded first, then metadata, users, and memories
  await fetchCompany();
  await loadApiKey();
  // Force a DOM update to ensure reactivity is properly triggered
  await nextTick();
  await Promise.all([fetchMetadata(companyId), fetchUsers(companyId), fetchMemories(companyId)]);

  // Start polling for RAG status
  startRagStatusPolling();
});

onUnmounted(() => {
  // Clean up polling when component is unmounted
  stopRagStatusPolling();
});

watchEffect(async () => {
  // Only re-fetch if companyId changes and company data is available
  if (companyId && company.value) {
    await Promise.all([fetchMetadata(companyId), fetchUsers(companyId), fetchMemories(companyId)]);

    // Only start polling if not already running
    if (!ragStatusPollInterval) {
      startRagStatusPolling();
    } else {
      // Just fetch once to update status
      fetchRagStatus();
    }
  }
});

const startAddingMetadata = () => {
  router.push({
    name: "EditMetadata",
    params: {
      companyId,
      metadataId: "new",
    },
  });
};

const editMetadata = (doc) => {
  router.push({
    name: "EditMetadata",
    params: {
      companyId,
      metadataId: doc._id?.$oid,
    },
  });
};

const editCompany = () => {
  router.push({
    name: "EditCompany",
    params: {
      companyId,
    },
  });
};

const startAddingUser = () => {
  router.push({
    name: "EditUser",
    params: {
      companyId,
      userId: "new",
    },
  });
};

const editUser = (user) => {
  router.push({
    name: "EditUser",
    params: {
      companyId,
      userId: user._id?.$oid,
    },
  });
};

const connectGoogleDrive = async () => {
  try {
    // This will open Google OAuth flow
    await store.dispatch("admin/connectGoogleDrive", companyId);
    // Refresh company data to show updated connection status
    await fetchCompany();

    // Automatically open folder manager on successful first-time connection
    showFolderManager.value = true;
  } catch (error) {
    console.error("Failed to connect Google Drive:", error);
    // Error handling is now done through the store's error state
  }
};

const syncGoogleDrive = async () => {
  // Check if any folders are selected before syncing
  if (!company.value?.google_drive?.folder_count || company.value.google_drive.folder_count === 0) {
    // Show error message and don't proceed with sync
    store.commit("admin/SET_ERROR", "Please select at least one folder to monitor before syncing. Use the 'Manage Folders' button to select folders.");
    return;
  }

  try {
    isSyncing.value = true;
    lastSyncStatus.value = null;

    await store.dispatch("admin/syncGoogleDrive", companyId);
    await fetchCompany();

    // Restart polling since new files may be added
    if (!ragStatusPollInterval) {
      startRagStatusPolling();
    } else {
      // Force an immediate fetch to update status
      fetchRagStatus();
    }

    // Show success indicator permanently
    lastSyncStatus.value = "success";
  } catch (error) {
    console.error("Failed to sync Google Drive:", error);
    lastSyncStatus.value = "error";

    // Check if the error is about folder selection or file count
    const errorData = error.response?.data;
    if (errorData?.requires_folder_selection) {
      store.commit("admin/SET_ERROR", "Please select at least one folder to monitor before syncing. Use the 'Manage Folders' button to select folders.");
    } else if (errorData?.validation_error === "too_many_files") {
      store.commit(
        "admin/SET_ERROR",
        `Too many files selected for sync (${errorData.file_count} files found). Please reduce the number of selected folders using the 'Manage Folders' button. Maximum 100 files recommended.`
      );
    } else {
      // Generic error handling
      store.commit("admin/SET_ERROR", error.response?.data?.error || "Failed to sync Google Drive. Please try again.");
    }
  } finally {
    isSyncing.value = false;
  }
};

const disconnectGoogleDrive = async () => {
  try {
    isDisconnectingGoogleDrive.value = true;

    const result = await store.dispatch("admin/disconnectGoogleDrive", {
      companyId,
      removeSyncedFiles: removeSyncedFiles.value,
    });

    // Close modal and refresh company data
    showDisconnectModal.value = false;
    removeSyncedFiles.value = false;
    await fetchCompany();

    // Refresh metadata list if files were removed
    if (removeSyncedFiles.value) {
      await fetchMetadata(companyId);
    }

    // Success - no popup needed, the UI will reflect the changes
  } catch (error) {
    console.error("Failed to disconnect Google Drive:", error);
    // Only show alert on failure
    alert("Failed to disconnect Google Drive. Please try again.");
  } finally {
    isDisconnectingGoogleDrive.value = false;
  }
};

const manageFolders = () => {
  showFolderManager.value = true;
};

const onFolderManagerClose = () => {
  showFolderManager.value = false;
};

const onCloudFoldersSaved = async (selectedFolders, provider) => {
  // Refresh company data to show updated folder count
  await fetchCompany();

  // Always refresh metadata list since files may have been removed from unselected folders
  await fetchMetadata(companyId);

  // Only trigger sync if folders are actually selected
  if (selectedFolders.length > 0) {
    // Add a small delay to ensure the database has been updated before syncing
    await new Promise((resolve) => setTimeout(resolve, 1000));

    // Fetch company data again to ensure we have the latest folder count
    await fetchCompany();

    // Automatically trigger sync after saving folders
    try {
      if (provider === "google_drive") {
        isSyncing.value = true;
        lastSyncStatus.value = null;
        await store.dispatch("admin/syncGoogleDrive", companyId);
        lastSyncStatus.value = "success";
      } else if (provider === "onedrive") {
        isSyncingOneDrive.value = true;
        lastOneDriveSyncStatus.value = null;
        await store.dispatch("admin/syncOneDrive", companyId);
        lastOneDriveSyncStatus.value = "success";
      }

      await fetchCompany(); // Refresh again to show sync status
    } catch (error) {
      const providerName = provider === "google_drive" ? "Google Drive" : "OneDrive";
      console.error(`Failed to sync ${providerName} after folder update:`, error);

      if (provider === "google_drive") {
        lastSyncStatus.value = "error";
      } else if (provider === "onedrive") {
        lastOneDriveSyncStatus.value = "error";
      }

      // Check if the error is about folder selection
      if (error.response?.data?.requires_folder_selection) {
        store.commit("admin/SET_ERROR", "Please select at least one folder to monitor before syncing.");
      }
    } finally {
      if (provider === "google_drive") {
        isSyncing.value = false;
      } else if (provider === "onedrive") {
        isSyncingOneDrive.value = false;
      }
    }
  } else {
    // Clear any success status when no folders are selected
    if (provider === "google_drive") {
      lastSyncStatus.value = null;
    } else if (provider === "onedrive") {
      lastOneDriveSyncStatus.value = null;
    }
    // Show info message about folder selection
    store.commit("admin/SET_ERROR", "Folder selection updated. Select at least one folder to enable syncing.");
  }
};

// OneDrive integration methods
const connectOneDrive = async () => {
  try {
    // This will open OneDrive OAuth flow
    await store.dispatch("admin/connectOneDrive", companyId);
    // Refresh company data to show updated connection status
    await fetchCompany();

    // Automatically open folder manager on successful first-time connection
    showOneDriveFolderManager.value = true;
  } catch (error) {
    console.error("Failed to connect OneDrive:", error);
    // Error handling is done through the store's error state
  }
};

const syncOneDrive = async () => {
  // Check if any folders are selected before syncing
  if (!company.value?.onedrive?.folder_count || company.value.onedrive.folder_count === 0) {
    // Show error message and don't proceed with sync
    store.commit("admin/SET_ERROR", "Please select at least one folder to monitor before syncing. Use the 'Manage Folders' button to select folders.");
    return;
  }

  try {
    isSyncingOneDrive.value = true;
    lastOneDriveSyncStatus.value = null;

    await store.dispatch("admin/syncOneDrive", companyId);
    await fetchCompany();

    // Restart polling since new files may be added
    if (!ragStatusPollInterval) {
      startRagStatusPolling();
    } else {
      // Force an immediate fetch to update status
      fetchRagStatus();
    }

    // Show success indicator permanently
    lastOneDriveSyncStatus.value = "success";
  } catch (error) {
    console.error("Failed to sync OneDrive:", error);
    lastOneDriveSyncStatus.value = "error";

    // Check if the error is about folder selection
    if (error.response?.data?.requires_folder_selection) {
      store.commit("admin/SET_ERROR", "Please select at least one folder to monitor before syncing. Use the 'Manage Folders' button to select folders.");
    }
  } finally {
    isSyncingOneDrive.value = false;
  }
};

const disconnectOneDrive = async () => {
  try {
    isDisconnectingOneDrive.value = true;

    const result = await store.dispatch("admin/disconnectOneDrive", {
      companyId,
      removeSyncedFiles: removeSyncedOneDriveFiles.value,
    });

    // Close modal and refresh company data
    showOneDriveDisconnectModal.value = false;
    removeSyncedOneDriveFiles.value = false;
    await fetchCompany();

    // Refresh metadata list if files were removed
    if (removeSyncedOneDriveFiles.value) {
      await fetchMetadata(companyId);
    }

    // Success - no popup needed, the UI will reflect the changes
  } catch (error) {
    console.error("Failed to disconnect OneDrive:", error);
    // Only show alert on failure
    alert("Failed to disconnect OneDrive. Please try again.");
  } finally {
    isDisconnectingOneDrive.value = false;
  }
};

const manageOneDriveFolders = () => {
  showOneDriveFolderManager.value = true;
};

const onOneDriveFolderManagerClose = () => {
  showOneDriveFolderManager.value = false;
};

// Email integration methods
const closeEmailConnectionModal = () => {
  showEmailConnectionModal.value = false;
  showGenericIMAPForm.value = false;
  imapForm.value = {
    email: "",
    password: "",
    server: "",
    port: 993,
    ssl: true,
  };
};

const connectEmail = async (provider) => {
  try {
    // This will open email OAuth flow for Gmail/Microsoft
    await store.dispatch("admin/connectEmail", { companyId, provider });
    // Modal will close automatically on success
    closeEmailConnectionModal();
    // Refresh company data to show updated connection status
    await fetchCompany();

    // Automatically sync emails after successful connection
    await syncEmails();
  } catch (error) {
    console.error(`Failed to connect ${provider}:`, error);
    // Error handling is done through the store's error state
  }
};

const connectGenericIMAP = async () => {
  try {
    isConnectingEmail.value = true;

    await store.dispatch("admin/connectGenericEmail", {
      companyId,
      credentials: {
        email_address: imapForm.value.email,
        password: imapForm.value.password,
        imap_server: imapForm.value.server,
        imap_port: imapForm.value.port,
        use_ssl: imapForm.value.ssl,
      },
    });

    closeEmailConnectionModal();
    await fetchCompany();

    // Automatically sync emails after successful connection
    await syncEmails();
  } catch (error) {
    console.error("Failed to connect generic IMAP:", error);
    // Error handling is done through the store's error state
  } finally {
    isConnectingEmail.value = false;
  }
};

const syncEmails = async () => {
  try {
    isSyncingEmails.value = true;
    lastEmailSyncStatus.value = null;

    await store.dispatch("admin/syncEmails", companyId);
    await fetchCompany();
    await fetchMetadata(companyId); // Refresh to show new emails

    // Restart polling since new emails may be added
    if (!ragStatusPollInterval) {
      startRagStatusPolling();
    } else {
      // Force an immediate fetch to update status
      fetchRagStatus();
    }

    // Show success indicator
    lastEmailSyncStatus.value = "success";
  } catch (error) {
    console.error("Failed to sync emails:", error);
    lastEmailSyncStatus.value = "error";
  } finally {
    isSyncingEmails.value = false;
  }
};

const disconnectEmail = async () => {
  try {
    isDisconnectingEmail.value = true;

    await store.dispatch("admin/disconnectEmail", {
      companyId,
      removeSyncedEmails: removeSyncedEmails.value,
    });

    // Close modal and refresh company data
    showEmailDisconnectModal.value = false;
    removeSyncedEmails.value = false;
    await fetchCompany();

    // Refresh metadata list if emails were removed
    if (removeSyncedEmails.value) {
      await fetchMetadata(companyId);
    }
  } catch (error) {
    console.error("Failed to disconnect email:", error);
    alert("Failed to disconnect email. Please try again.");
  } finally {
    isDisconnectingEmail.value = false;
  }
};

// Manual file upload methods
const triggerFileUpload = () => {
  fileInput.value.click();
};

const handleFileUpload = async (event) => {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  // Check file sizes before uploading (client-side validation)
  const maxFileSize = 25 * 1024 * 1024; // 25MB per file
  const oversizedFiles = [];

  for (let i = 0; i < files.length; i++) {
    if (files[i].size > maxFileSize) {
      oversizedFiles.push(files[i].name);
    }
  }

  if (oversizedFiles.length > 0) {
    const fileList = oversizedFiles.join(", ");
    store.commit("admin/SET_ERROR", `The following files are too large (max 25MB per file): ${fileList}`);
    fileInput.value.value = "";
    return;
  }

  try {
    isUploadingFiles.value = true;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }

    await store.dispatch("admin/uploadFiles", { companyId, formData });

    // Refresh company and metadata data
    await Promise.all([fetchCompany(), fetchMetadata(companyId)]);

    // Restart polling since new files were added
    if (!ragStatusPollInterval) {
      startRagStatusPolling();
    } else {
      // Force an immediate fetch to update status
      fetchRagStatus();
    }

    // Clear the file input
    fileInput.value.value = "";

    store.commit("admin/SET_ERROR", null);
  } catch (error) {
    console.error("Failed to upload files:", error);

    // Handle specific error types
    if (error.response?.status === 413) {
      const errorData = error.response.data;
      const maxSizeMB = errorData.max_size_mb || 50;
      store.commit("admin/SET_ERROR", `Upload failed: Total file size exceeds ${maxSizeMB}MB limit. Please select fewer or smaller files.`);
    } else if (error.response?.data?.message) {
      store.commit("admin/SET_ERROR", error.response.data.message);
    } else {
      store.commit("admin/SET_ERROR", "Failed to upload files. Please try again.");
    }
  } finally {
    isUploadingFiles.value = false;
  }
};

const deleteManualFile = async (file) => {
  if (!confirm(t("confirm_delete_file", { file: file.manual_upload?.file_name }))) {
    return;
  }

  try {
    isDeletingFiles.value = true;

    await store.dispatch("admin/deleteManualFile", {
      companyId,
      fileId: file._id?.$oid || file._id,
    });

    // Refresh company and metadata data
    await Promise.all([fetchCompany(), fetchMetadata(companyId)]);
  } catch (error) {
    console.error("Failed to delete file:", error);
  } finally {
    isDeletingFiles.value = false;
  }
};

const formatFileSize = (bytes) => {
  if (!bytes) return "0 B";

  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

const clearError = () => {
  store.commit("admin/SET_ERROR", null);
};

// Memory management methods
const deleteMemory = async (memory) => {
  if (!confirm(t("confirm_delete_memory"))) return;

  try {
    isDeletingMemories.value = true;
    await store.dispatch("admin/removeMemory", {
      memoryId: memory._id.$oid || memory._id,
      companyId: companyId,
    });
  } catch (error) {
    console.error("Failed to delete memory:", error);
    store.commit("admin/SET_ERROR", t("memory_delete_failed"));
  } finally {
    isDeletingMemories.value = false;
  }
};
</script>

<style scoped>
.phonenumber {
  display: inline-block;
  margin-right: 10px;
}

.collapse-content {
  border-left: 3px solid #e9ecef;
  padding-left: 15px;
  margin-left: 10px;
}

.btn-link:focus {
  box-shadow: none;
}

.btn-link:hover {
  text-decoration: none !important;
}

.memory-content {
  max-width: 400px;
  white-space: normal;
  word-wrap: break-word;
  line-height: 1.4;
}

.card {
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  border: 1px solid #dee2e6;
}

.card-title {
  color: #495057;
  font-weight: 600;
}

.badge {
  font-size: 0.75em;
}
</style>

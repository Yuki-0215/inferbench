{{- define "inferbench.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "inferbench.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "inferbench.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{ include "inferbench.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "inferbench.selectorLabels" -}}
app.kubernetes.io/name: {{ include "inferbench.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "inferbench.image" -}}
{{- $tag := required "image.tag is required; set it to an existing release tag such as vX.Y.Z" .Values.image.tag -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end }}

{{- define "inferbench.claimName" -}}
{{- default (include "inferbench.fullname" .) .Values.persistence.existingClaim -}}
{{- end }}

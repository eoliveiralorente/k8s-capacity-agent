{{- define "collector.name" -}}capacity-collector{{- end -}}
{{- define "collector.fullname" -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- define "collector.labels" -}}
app.kubernetes.io/name: {{ include "collector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
{{- define "collector.selector" -}}
app.kubernetes.io/name: {{ include "collector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "collector.secretName" -}}{{ .Values.existingSecret | default (printf "%s-token" (include "collector.fullname" .)) }}{{- end -}}

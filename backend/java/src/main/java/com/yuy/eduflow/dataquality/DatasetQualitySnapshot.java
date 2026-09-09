package com.yuy.eduflow.dataquality;

import java.time.LocalDateTime;

/** 一次训练语料清洗结果的统计快照。语料本身留在文件里，这里只留口径。 */
public class DatasetQualitySnapshot {

	private Long id;
	private String fingerprint;
	private String datasetDir;
	private Integer sourceFiles;
	private Integer occurrenceRows;
	private Integer teachingSessions;
	private Integer teachingTasks;
	private Integer duplicatesRemoved;
	private Integer trainableTasks;
	private Integer trainableSessions;
	private Integer jointTasks;
	private Integer eveningSessions;
	private String reportJson;
	private String capturedBy;
	private LocalDateTime createdAt;

	public Long getId() { return id; }
	public void setId(Long id) { this.id = id; }
	public String getFingerprint() { return fingerprint; }
	public void setFingerprint(String fingerprint) { this.fingerprint = fingerprint; }
	public String getDatasetDir() { return datasetDir; }
	public void setDatasetDir(String datasetDir) { this.datasetDir = datasetDir; }
	public Integer getSourceFiles() { return sourceFiles; }
	public void setSourceFiles(Integer sourceFiles) { this.sourceFiles = sourceFiles; }
	public Integer getOccurrenceRows() { return occurrenceRows; }
	public void setOccurrenceRows(Integer occurrenceRows) { this.occurrenceRows = occurrenceRows; }
	public Integer getTeachingSessions() { return teachingSessions; }
	public void setTeachingSessions(Integer teachingSessions) { this.teachingSessions = teachingSessions; }
	public Integer getTeachingTasks() { return teachingTasks; }
	public void setTeachingTasks(Integer teachingTasks) { this.teachingTasks = teachingTasks; }
	public Integer getDuplicatesRemoved() { return duplicatesRemoved; }
	public void setDuplicatesRemoved(Integer duplicatesRemoved) { this.duplicatesRemoved = duplicatesRemoved; }
	public Integer getTrainableTasks() { return trainableTasks; }
	public void setTrainableTasks(Integer trainableTasks) { this.trainableTasks = trainableTasks; }
	public Integer getTrainableSessions() { return trainableSessions; }
	public void setTrainableSessions(Integer trainableSessions) { this.trainableSessions = trainableSessions; }
	public Integer getJointTasks() { return jointTasks; }
	public void setJointTasks(Integer jointTasks) { this.jointTasks = jointTasks; }
	public Integer getEveningSessions() { return eveningSessions; }
	public void setEveningSessions(Integer eveningSessions) { this.eveningSessions = eveningSessions; }
	public String getReportJson() { return reportJson; }
	public void setReportJson(String reportJson) { this.reportJson = reportJson; }
	public String getCapturedBy() { return capturedBy; }
	public void setCapturedBy(String capturedBy) { this.capturedBy = capturedBy; }
	public LocalDateTime getCreatedAt() { return createdAt; }
	public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}

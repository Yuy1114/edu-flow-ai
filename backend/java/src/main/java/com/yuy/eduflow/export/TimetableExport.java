package com.yuy.eduflow.export;

/** 一次导出的产物：建议文件名与 xlsx 字节内容。 */
public record TimetableExport(String fileName, byte[] content) {
}

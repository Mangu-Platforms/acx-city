import React, { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText } from 'lucide-react'

interface FileUploadProps {
  onFileUpload: (file: File) => void
  disabled?: boolean
}

export const FileUpload: React.FC<FileUploadProps> = ({ onFileUpload, disabled }) => {
  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) onFileUpload(acceptedFiles[0])
  }, [onFileUpload])

  const { getRootProps, getInputProps, isDragActive, acceptedFiles } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx']
    },
    multiple: false,
    disabled
  })

  const file = acceptedFiles[0]

  return (
    <div
      {...getRootProps()}
      className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
        isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-gray-50 hover:border-gray-400'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <input {...getInputProps()} />
      <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
      {file ? (
        <div className="flex items-center justify-center space-x-2">
          <FileText className="h-5 w-5 text-green-500" />
          <span className="text-sm font-medium text-gray-700">{file.name}</span>
        </div>
      ) : (
        <div>
          <p className="text-lg font-medium text-gray-700 mb-2">
            {isDragActive ? 'Drop the file here' : 'Upload your book'}
          </p>
          <p className="text-sm text-gray-500">Drag &amp; drop a .docx, .txt or .pdf, or click to select</p>
          <p className="text-xs text-gray-400 mt-2">DOCX headings become chapters automatically</p>
        </div>
      )}
    </div>
  )
}

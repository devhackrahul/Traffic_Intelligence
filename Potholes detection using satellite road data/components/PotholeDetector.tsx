'use client'

import { useState, useRef, useEffect } from 'react'
import { detectPotholes } from '@/lib/detection'

interface PotholeDetectorProps {
  location: { lat: number; lng: number } | null
}

interface Detection {
  x: number
  y: number
  width: number
  height: number
  confidence: number
}

export default function PotholeDetector({ location }: PotholeDetectorProps) {
  const [inputType, setInputType] = useState<'video' | 'image'>('video')
  const [isDetecting, setIsDetecting] = useState(false)
  const [detections, setDetections] = useState<Detection[]>([])
  const [status, setStatus] = useState<string>('')
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.7)
  
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const streamRef = useRef<MediaStream | null>(null)

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop())
      }
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl)
      }
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl)
      }
    }
  }, [videoUrl, imageUrl])

  useEffect(() => {
    if (canvasRef.current && (videoRef.current || imageUrl)) {
      drawDetections()
    }
  }, [detections, imageUrl])

  const drawDetections = () => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const source = inputType === 'video' ? videoRef.current : null
    const img = inputType === 'image' && imageUrl ? new Image() : null

    if (inputType === 'image' && img && imageUrl) {
      img.onload = () => {
        canvas.width = img.width
        canvas.height = img.height
        ctx.clearRect(0, 0, canvas.width, canvas.height)
        ctx.drawImage(img, 0, 0)
        drawBoundingBoxes(ctx, canvas.width, canvas.height)
      }
      img.src = imageUrl
    } else if (source && source.videoWidth > 0) {
      canvas.width = source.videoWidth
      canvas.height = source.videoHeight
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(source, 0, 0)
      drawBoundingBoxes(ctx, canvas.width, canvas.height)
    }
  }

  const drawBoundingBoxes = (ctx: CanvasRenderingContext2D, width: number, height: number) => {
    detections.forEach((detection) => {
      const x = (detection.x / 100) * width
      const y = (detection.y / 100) * height
      const w = (detection.width / 100) * width
      const h = (detection.height / 100) * height

      ctx.strokeStyle = '#ff0000'
      ctx.lineWidth = 3
      ctx.strokeRect(x, y, w, h)

      ctx.fillStyle = '#ff0000'
      ctx.font = '16px Arial'
      ctx.fillText(
        `Pothole ${Math.round(detection.confidence * 100)}%`,
        x,
        y > 20 ? y - 5 : y + 20
      )
    })
  }

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        setVideoUrl(null)
      }
      setStatus('Camera started. Click "Detect Potholes" to begin detection.')
    } catch (error) {
      setStatus('Error accessing camera: ' + (error as Error).message)
    }
  }

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (inputType === 'image') {
      const url = URL.createObjectURL(file)
      setImageUrl(url)
      setVideoUrl(null)
      stopCamera()
    } else {
      const url = URL.createObjectURL(file)
      setVideoUrl(url)
      setImageUrl(null)
      stopCamera()
      if (videoRef.current) {
        videoRef.current.srcObject = null
        videoRef.current.src = url
      }
    }
  }

  const captureFrame = (): string | null => {
    if (inputType === 'image' && imageUrl) {
      return imageUrl
    }

    const video = videoRef.current
    if (!video || video.videoWidth === 0) return null

    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return null

    ctx.drawImage(video, 0, 0)
    return canvas.toDataURL('image/jpeg')
  }

  const handleDetect = async () => {
    setIsDetecting(true)
    setStatus('Detecting potholes...')
    setDetections([])

    try {
      const frame = captureFrame()
      if (!frame) {
        setStatus('Error: No video/image available')
        setIsDetecting(false)
        return
      }

      const results = await detectPotholes(frame)
      // Filter by confidence threshold
      const filteredResults = results.filter(d => d.confidence >= confidenceThreshold)
      setDetections(filteredResults)
      setStatus(`Detection complete! Found ${filteredResults.length} pothole(s) (${results.length} total, filtered by ${Math.round(confidenceThreshold * 100)}% confidence).`)
      
      if (inputType === 'video' && videoRef.current) {
        const interval = setInterval(async () => {
            const newFrame = captureFrame()
            if (newFrame) {
              const newResults = await detectPotholes(newFrame)
              const filtered = newResults.filter(d => d.confidence >= confidenceThreshold)
              setDetections(filtered)
            }
        }, 1000)

        setTimeout(() => clearInterval(interval), 30000)
      }
    } catch (error) {
      setStatus('Detection error: ' + (error as Error).message)
    } finally {
      setIsDetecting(false)
    }
  }

  return (
    <div>
      <div className="input-group">
        <label>Input Type</label>
        <div className="controls">
          <button
            className={`button ${inputType === 'video' ? '' : 'button-secondary'}`}
            onClick={() => {
              setInputType('video')
              setDetections([])
              setImageUrl(null)
            }}
          >
            Video
          </button>
          <button
            className={`button ${inputType === 'image' ? '' : 'button-secondary'}`}
            onClick={() => {
              setInputType('image')
              setDetections([])
              stopCamera()
              setVideoUrl(null)
            }}
          >
            Image
          </button>
        </div>
      </div>

      {inputType === 'video' && (
        <div className="input-group">
          <div className="controls">
            <button className="button" onClick={startCamera}>
              Start Camera
            </button>
            <button className="button button-secondary" onClick={stopCamera}>
              Stop Camera
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <button
              className="button button-secondary"
              onClick={() => fileInputRef.current?.click()}
            >
              Upload Video
            </button>
          </div>
        </div>
      )}

      {inputType === 'image' && (
        <div className="input-group">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileSelect}
          />
        </div>
      )}

      <div className="input-group">
        <label>Confidence Threshold: {Math.round(confidenceThreshold * 100)}%</label>
        <input
          type="range"
          min="0.3"
          max="0.9"
          step="0.05"
          value={confidenceThreshold}
          onChange={(e) => setConfidenceThreshold(parseFloat(e.target.value))}
          style={{ width: '100%', marginTop: '8px' }}
        />
        <small style={{ color: '#666', display: 'block', marginTop: '4px' }}>
          Higher values reduce false positives but may miss some potholes
        </small>
      </div>

      <div className="controls">
        <button
          className="button"
          onClick={handleDetect}
          disabled={isDetecting || (!videoRef.current?.srcObject && !videoUrl && !imageUrl)}
        >
          {isDetecting ? (
            <>
              <span className="loading" style={{ marginRight: '8px' }}></span>
              Detecting...
            </>
          ) : (
            'Detect Potholes'
          )}
        </button>
      </div>

      {status && (
        <div className={`status ${isDetecting ? 'detecting' : detections.length > 0 ? 'success' : ''}`}>
          {status}
        </div>
      )}

      <div className="preview-container">
        {inputType === 'video' && (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            style={{ width: '100%', height: 'auto' }}
          />
        )}
        {inputType === 'image' && imageUrl && (
          <img src={imageUrl} alt="Preview" style={{ width: '100%', height: 'auto' }} />
        )}
        <canvas ref={canvasRef} style={{ position: 'absolute', top: 0, left: 0 }} />
      </div>

      {detections.length > 0 && (
        <div className="detection-info">
          <h3>Detection Results</h3>
          <p>Found {detections.length} pothole(s)</p>
          {location && (
            <p>Location: {location.lat.toFixed(6)}, {location.lng.toFixed(6)}</p>
          )}
          {detections.map((det, idx) => (
            <p key={idx}>
              Pothole {idx + 1}: {Math.round(det.confidence * 100)}% confidence
            </p>
          ))}
        </div>
      )}
    </div>
  )
}


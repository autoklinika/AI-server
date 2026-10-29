package pl.autoklinika.magazyn

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.util.Base64
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.net.http.SslError
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.exifinterface.media.ExifInterface
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.ByteArrayOutputStream

/**
 * Native Android container for existing production WebGUI.
 *
 * Security: exact HTTPS origin, no JavaScriptInterface, no arbitrary URL schemes,
 * no WebView SSL bypass. Camera is launched only from the trusted ECU form.
 * No inventory write happens during scanning; WebGUI performs normal validation.
 */
class MainActivity : ComponentActivity() {
    private companion object {
        const val MAGAZYN_URL = "https://ai-server.tail759e12.ts.net:8443/"
        const val MAGAZYN_HOST = "ai-server.tail759e12.ts.net"
    }

    private lateinit var browser: WebView
    private lateinit var offlinePanel: LinearLayout
    private lateinit var offlineMessage: TextView
    private var pendingPhoto: File? = null
    private var selectedFiles: ValueCallback<Array<Uri>>? = null

    private val photograph = registerForActivityResult(ActivityResultContracts.TakePicture()) { success ->
        val file = pendingPhoto
        pendingPhoto = null
        if (success && file != null) {
            recognizeLabel(file)
        } else {
            file?.delete()
        }
    }

    private val chooseFile = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val callback = selectedFiles
        selectedFiles = null
        callback?.onReceiveValue(
            WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WebView.setWebContentsDebuggingEnabled(false)

        val root = FrameLayout(this)
        browser = WebView(this)
        root.addView(
            browser,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
        createOfflinePanel(root)
        setContentView(root)

        configureBrowser()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (!isTrusted(Uri.parse(browser.url ?: ""))) {
                    finish()
                    return
                }
                browser.evaluateJavascript(
                    "(function(){const d=[...document.querySelectorAll('dialog[open]')].pop();" +
                        "if(d){d.close();return true;}return false;})()"
                ) { closed ->
                    if (closed != "true") {
                        if (browser.canGoBack()) browser.goBack() else finish()
                    }
                }
            }
        })

        if (savedInstanceState == null || browser.restoreState(savedInstanceState) == null) {
            browser.loadUrl(MAGAZYN_URL)
        }
    }

    private fun configureBrowser() {
        browser.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true // User-selected content:// files for existing WebGUI attachments.
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            cacheMode = WebSettings.LOAD_DEFAULT
            setGeolocationEnabled(false)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, false)

        browser.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (uri.scheme == "magazyn-scan") {
                    if (request.isForMainFrame &&
                        uri.host == "capture" &&
                        isTrusted(Uri.parse(view.url ?: ""))
                    ) {
                        startCamera()
                    }
                    return true
                }
                if (isTrusted(uri)) return false
                if (request.isForMainFrame && (uri.scheme == "https" || uri.scheme == "http")) {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, uri))
                    } catch (_: ActivityNotFoundException) {
                        toast("Brak przeglądarki do otwarcia odnośnika.")
                    }
                }
                // Deny file:, intent:, javascript:, content:, untrusted frames, etc.
                return true
            }

            override fun onPageFinished(view: WebView, url: String?) {
                if (isTrusted(Uri.parse(url ?: ""))) {
                    hideOfflinePanel()
                    // Only inject into the exact trusted Magazyn origin.
                    val bridge = assets.open("ecu-scan-bridge.js")
                        .bufferedReader(Charsets.UTF_8).use { it.readText() }
                    view.evaluateJavascript(bridge, null)
                }
            }

            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                if (request.isForMainFrame) {
                    showOfflinePanel("Nie można połączyć się z Magazynem. Włącz Tailscale i spróbuj ponownie.")
                }
            }

            override fun onReceivedSslError(
                view: WebView, handler: SslErrorHandler, error: SslError
            ) {
                handler.cancel()
                showOfflinePanel("Błąd certyfikatu HTTPS. Połączenie zostało zablokowane.")
            }
        }

        browser.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                if (!isTrusted(Uri.parse(webView.url ?: ""))) {
                    filePathCallback.onReceiveValue(null)
                    return true
                }
                selectedFiles?.onReceiveValue(null)
                selectedFiles = filePathCallback
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    putExtra(
                        Intent.EXTRA_ALLOW_MULTIPLE,
                        fileChooserParams.mode == FileChooserParams.MODE_OPEN_MULTIPLE
                    )
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                try {
                    chooseFile.launch(intent)
                } catch (_: ActivityNotFoundException) {
                    selectedFiles = null
                    filePathCallback.onReceiveValue(null)
                    toast("Nie znaleziono aplikacji do wyboru pliku.")
                }
                return true
            }
        }
    }

    private fun isTrusted(uri: Uri?): Boolean =
        uri?.scheme == "https" &&
            uri.host.equals(MAGAZYN_HOST, ignoreCase = true) &&
            uri.port == 8443 &&
            !uri.authority.orEmpty().contains("@")

    private fun startCamera() {
        val dialogIsOpen = "document.getElementById('item-dialog')?.open === true"
        browser.evaluateJavascript(dialogIsOpen) { open ->
            if (open != "true" || !isTrusted(Uri.parse(browser.url ?: ""))) return@evaluateJavascript
            val directory = File(cacheDir, "camera").apply { mkdirs() }
            val file = File.createTempFile("ecu-", ".jpg", directory)
            pendingPhoto = file
            val uri = FileProvider.getUriForFile(
                this, "pl.autoklinika.magazyn.fileprovider", file
            )
            try {
                photograph.launch(uri)
            } catch (_: ActivityNotFoundException) {
                file.delete()
                pendingPhoto = null
                toast("Na telefonie nie znaleziono aplikacji aparatu.")
            } catch (_: SecurityException) {
                file.delete()
                pendingPhoto = null
                toast("Nie można udostępnić zdjęcia aplikacji aparatu.")
            }
        }
    }

    private fun encodePhotoForAi(file: File): String? {
        // Downscale only if needed, while keeping small factory label glyphs legible.
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 2600) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = BitmapFactory.decodeFile(file.absolutePath, options) ?: return null
        val orientation = ExifInterface(file.absolutePath).getAttributeInt(
            ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL
        )
        val degrees = when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        val rotated = if (degrees != 0f) {
            val matrix = Matrix().apply { postRotate(degrees) }
            Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        } else decoded
        val factor = minOf(1.0, 2400.0 / maxOf(rotated.width, rotated.height))
        val reduced = if (factor < 1.0) {
            Bitmap.createScaledBitmap(
                rotated,
                (rotated.width * factor).toInt().coerceAtLeast(1),
                (rotated.height * factor).toInt().coerceAtLeast(1),
                true
            )
        } else rotated
        if (reduced !== rotated) rotated.recycle()
        if (rotated !== decoded) decoded.recycle()
        val result = ByteArrayOutputStream()
        try {
            var quality = 89
            do {
                result.reset()
                reduced.compress(Bitmap.CompressFormat.JPEG, quality, result)
                quality -= 7
            } while (result.size() > 3_000_000 && quality >= 61)
            return if (result.size() <= 3_000_000) {
                Base64.encodeToString(result.toByteArray(), Base64.NO_WRAP)
            } else null
        } finally {
            reduced.recycle()
            result.close()
        }
    }

    private fun recognizeLabel(file: File) {
        val uri = Uri.fromFile(file)
        val image = try {
            InputImage.fromFilePath(this, uri)
        } catch (_: Exception) {
            file.delete()
            toast("Nie udało się otworzyć wykonanego zdjęcia.")
            return
        }
        toast("Odczytuję etykietę ECU...")
        val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        val scanner = BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_ALL_FORMATS).build()
        )
        val textTask = recognizer.process(image)
        val codeTask = scanner.process(image)
        Tasks.whenAllComplete(textTask, codeTask).addOnCompleteListener {
            val text = if (textTask.isSuccessful) textTask.result.text else ""
            val codes = if (codeTask.isSuccessful) {
                codeTask.result.mapNotNull { it.rawValue }
            } else emptyList()
            recognizer.close()
            scanner.close()
            // Image preprocessing is off the UI thread, with no disk persistence.
            Thread {
                val jpeg = try { encodePhotoForAi(file) } catch (_: Exception) { null }
                file.delete()
                runOnUiThread {
                    if (!isTrusted(Uri.parse(browser.url ?: ""))) return@runOnUiThread
                    val data = EcuLabelParser.parse(text, codes)
                    val json = JSONObject().apply {
                        put("manufacturer", data.manufacturer)
                        put("primaryNumber", data.primaryNumber)
                        put("hardware", data.hardware)
                        put("software", data.software)
                        put("model", data.model)
                        put("candidates", JSONArray(data.candidates))
                        put("barcodes", JSONArray(data.barcodes))
                        put("rawText", data.rawText)
                        put("jpegBase64", jpeg ?: "")
                    }
                    // Quoted JSON string prevents script injection via recognized text.
                    browser.evaluateJavascript(
                        "window.magazynRequestAiScan && window.magazynRequestAiScan(" +
                            JSONObject.quote(json.toString()) + ")",
                        null
                    )
                }
            }.start()
        }
    }

    private fun createOfflinePanel(root: FrameLayout) {
        offlinePanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(28), dp(24), dp(28), dp(24))
            setBackgroundColor(Color.rgb(245, 245, 244))
            visibility = View.GONE
        }
        val title = TextView(this).apply {
            text = "Magazyn V1"
            textSize = 24f
            setTextColor(Color.rgb(40, 45, 51))
            gravity = Gravity.CENTER
        }
        offlineMessage = TextView(this).apply {
            textSize = 16f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(75, 83, 92))
            setPadding(0, dp(20), 0, dp(20))
        }
        val retry = Button(this).apply {
            text = "Spróbuj ponownie"
            setOnClickListener {
                hideOfflinePanel()
                browser.loadUrl(MAGAZYN_URL)
            }
        }
        offlinePanel.addView(title)
        offlinePanel.addView(offlineMessage)
        offlinePanel.addView(retry)
        root.addView(
            offlinePanel,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
    }

    private fun showOfflinePanel(message: String) {
        offlineMessage.text = message
        offlinePanel.visibility = View.VISIBLE
    }

    private fun hideOfflinePanel() {
        offlinePanel.visibility = View.GONE
    }

    private fun dp(value: Int) = (resources.displayMetrics.density * value).toInt()

    private fun toast(message: String) =
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()

    override fun onPause() {
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        browser.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        selectedFiles?.onReceiveValue(null)
        selectedFiles = null
        pendingPhoto?.delete()
        browser.destroy()
        super.onDestroy()
    }
}

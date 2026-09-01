<?php

use Illuminate\Support\Facades\Route;
use App\Http\Middleware\JwtMiddleware;
use App\Http\Controllers\Api\CodeController;
use App\Http\Controllers\Api\ScanController;
use App\Http\Controllers\Auth\AuthController;
use App\Http\Controllers\Api\CarMismatchReportController;
use App\Http\Controllers\Api\ApplogController;

// Route::get('/user', function (Request $request) {
//     return $request->user();
// })->middleware('auth:sanctum');

Route::prefix('auth')->group(function () {
    Route::post('/companyCode', [AuthController::class, 'companyCode']);
    Route::post('/register', [AuthController::class, 'register']);
    Route::post('/registerValidate', [AuthController::class, 'registerValidate']);
    Route::post('/requestSms', [AuthController::class, 'requestSms']);
    Route::post('/verifySms', [AuthController::class, 'verifySms']);
    Route::post('/findTid', [AuthController::class, 'findTid']);
    Route::post('/setPasswordByVerifySms', [AuthController::class, 'setPasswordByVerifySms']);
    Route::post('/login', [AuthController::class, 'login']);
    Route::post('/refresh', [AuthController::class, 'refresh']);

    Route::middleware(JwtMiddleware::class)
        ->group(function () {
            Route::post('/logout', [AuthController::class, 'logout']);
            Route::get('/me', [AuthController::class, 'me']);
            Route::post('/invalidateAllTokens', [AuthController::class, 'invalidateAllTokens']);
            Route::post('/setMobile', [AuthController::class, 'setMobile']);
            Route::post('/setPassword', [AuthController::class, 'setPassword']);
            Route::post('/withdraw', [AuthController::class, 'withdraw']);
            // Route::post('/log', [AuthController::class, 'log']);
        });
});

Route::middleware(JwtMiddleware::class)
    ->group(function () {
        Route::apiResource('scans', ScanController::class);

        Route::post('/scans/getCarInfo', [ScanController::class, 'getCarInfo']);
        Route::post('scans/{scan}/email', [ScanController::class, 'sendEmail']);
        Route::get('scans/{scan}/pdf', [ScanController::class, 'generatePdf']);

        Route::apiResource('carMismatchReports', CarMismatchReportController::class)
            ->only(['index', 'show', 'store']);

        Route::apiResource('codes', CodeController::class)
            ->only(['index', 'show']);

        Route::apiResource('applogs', ApplogController::class)->only(['index', 'store', 'show']);
    });

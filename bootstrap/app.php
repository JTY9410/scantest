<?php

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use App\Http\Middleware\RequestSnakeCaseMiddleware;
use App\Http\Middleware\ResponseCamelCaseMiddleware;
use App\Http\Middleware\RequestDocsCleanupMiddleware;
use App\Http\Middleware\RequestResponseLoggerMiddleware;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware) {
        // 포트 제외 (X-Forwarded-Port 무시)
        $middleware->trustProxies(
            at: '*',
            headers: \Illuminate\Http\Request::HEADER_X_FORWARDED_FOR |
                     \Illuminate\Http\Request::HEADER_X_FORWARDED_HOST |
                     \Illuminate\Http\Request::HEADER_X_FORWARDED_PROTO
        );

        $middleware->group('api', [
            // RequestResponseLoggerMiddleware::class . ':start', // 시작점 로깅
            RequestSnakeCaseMiddleware::class,
            // RequestResponseLoggerMiddleware::class . ':after_snake_case', // snake_case 변환 후
            \Rakutentech\LaravelRequestDocs\LaravelRequestDocsMiddleware::class,
            // RequestResponseLoggerMiddleware::class . ':after_request_docs', // request-docs 처리 후
            ResponseCamelCaseMiddleware::class,
            // RequestResponseLoggerMiddleware::class . ':after_camel_case', // camelCase 변환 후
            RequestDocsCleanupMiddleware::class, // request-docs 경로아니면 LRD 미들웨어 내용 제거
            // RequestResponseLoggerMiddleware::class . ':end', // 최종 로깅
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions) {
        //
    })->create();

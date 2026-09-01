<?php

namespace App\Providers;

use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        if (getenv('VERCEL')) {
            $this->app->useStoragePath('/tmp/storage');
        }
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        if (getenv('VERCEL')) {
            foreach (['framework/cache', 'framework/sessions', 'framework/views', 'logs'] as $directory) {
                $path = '/tmp/storage/'.$directory;

                if (! is_dir($path)) {
                    mkdir($path, 0755, true);
                }
            }
        }
    }
}
